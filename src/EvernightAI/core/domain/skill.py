import json
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import Unresolvable

from EvernightAI.core.error.skill import (
    SkillConfigurationError,
    SkillConflictError,
    SkillDisabledError,
    SkillInputError,
    SkillNotFoundError,
    SkillRenderError,
)
from EvernightAI.core.protocol.skill import (
    SkillManageProtocol,
    SkillRegisterProtocol,
    SkillRendererProtocol,
    SkillTemplateFactoryProtocol,
    SkillTemplateStoreProtocol,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
    SkillTemplateConfig,
    SkillTemplateUpdate,
)


class SkillRegister(SkillRegisterProtocol):
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._renderers: dict[str, SkillRendererProtocol] = {}

    def register(
        self,
        skill: SkillDefinition,
        renderer: SkillRendererProtocol,
    ) -> None:
        _input_validator(skill)
        self._skills[skill.name] = skill
        self._renderers[skill.name] = renderer

    def unregister(self, skill_name: str) -> None:
        if not self.has(skill_name):
            raise SkillNotFoundError(f"The skill {skill_name} is not registered")
        self._skills.pop(skill_name, None)
        self._renderers.pop(skill_name, None)

    def get(self, skill_name: str) -> SkillDefinition:
        if self.has(skill_name):
            return self._skills[skill_name]
        raise SkillNotFoundError(f"The skill {skill_name} is not found")

    def get_renderer(self, skill_name: str) -> SkillRendererProtocol:
        if self.has(skill_name):
            return self._renderers[skill_name]
        raise SkillNotFoundError(f"The skill {skill_name} is not registered")

    def has(self, skill_name: str) -> bool:
        return skill_name in self._skills and skill_name in self._renderers

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())


class SkillManager(SkillManageProtocol):
    def __init__(
        self, register: SkillRegisterProtocol, *,
        template_factory: SkillTemplateFactoryProtocol | None = None,
        template_store: SkillTemplateStoreProtocol | None = None,
    ) -> None:
        self._register = register
        self._template_factory = template_factory
        self._template_store = template_store
        self._templates: dict[str, SkillTemplateConfig] = {}

    def list_skills(self) -> list[SkillDefinition]:
        return [skill.model_copy(deep=True) for skill in self._register.list_skills()]

    def get_skill(self, skill_name: str) -> SkillDefinition:
        return self._register.get(skill_name).model_copy(deep=True)

    def supports(self, skill_name: str, capability: SkillCapability) -> bool:
        skill = self._register.get(skill_name)
        return skill.is_enabled and capability in skill.capabilities

    def _build_template(self, config: SkillTemplateConfig) -> tuple[SkillDefinition, SkillRendererProtocol]:
        if self._template_factory is None:
            raise SkillConfigurationError("Skill template creation is not configured")
        definition = SkillDefinition.model_validate(config.model_dump(exclude={"prompt"}))
        definition.is_template = True
        _input_validator(definition)
        return definition, self._template_factory(config.model_copy(deep=True))

    def create_template(self, config: SkillTemplateConfig) -> SkillDefinition:
        if self._register.has(config.name):
            raise SkillConflictError(f"The skill {config.name} already exists")
        config = config.model_copy(deep=True)
        config.is_template = True
        config.revision = uuid4().hex
        definition, renderer = self._build_template(config)
        if self._template_store is not None:
            self._template_store.save(config)
        self._register.register(definition, renderer)
        self._templates[config.name] = config
        return definition.model_copy(deep=True)

    def get_template(self, skill_name: str) -> SkillTemplateConfig:
        self._register.get(skill_name)
        if skill_name not in self._templates:
            raise SkillConfigurationError(f"The skill {skill_name} is read-only")
        return self._templates[skill_name].model_copy(deep=True)

    def update_template(self, skill_name: str, update: SkillTemplateUpdate) -> SkillDefinition:
        current = self.get_template(skill_name)
        config = SkillTemplateConfig.model_validate({
            **current.model_dump(), **update.model_dump(exclude_unset=True),
        })
        if config != current:
            config.revision = uuid4().hex
        definition, renderer = self._build_template(config)
        if self._template_store is not None:
            self._template_store.save(config)
        self._register.register(definition, renderer)
        self._templates[skill_name] = config
        return definition.model_copy(deep=True)

    def delete_template(self, skill_name: str) -> None:
        self.get_template(skill_name)
        if self._template_store is not None:
            self._template_store.delete(skill_name)
        self._register.unregister(skill_name)
        del self._templates[skill_name]

    def restore(self) -> None:
        if self._template_store is None:
            return
        for config in self._template_store.list_configs():
            if self._register.has(config.name) and config.name not in self._templates:
                raise SkillConflictError(f"The stored skill {config.name} conflicts with a registered skill")
            config = config.model_copy(deep=True)
            needs_revision = config.revision is None
            if needs_revision:
                config.revision = uuid4().hex
            definition, renderer = self._build_template(config)
            if needs_revision:
                self._template_store.save(config)
            self._register.register(definition, renderer)
            self._templates[config.name] = config.model_copy(deep=True)

    def close(self) -> None:
        if self._template_store is not None:
            self._template_store.close()

    def is_ready(self) -> bool:
        return self._template_store is None or self._template_store.is_ready()

    def validate_input(self, request: SkillRenderRequest) -> None:
        if not request.skill_name.strip():
            raise SkillInputError("The skill render request must include a skill name")
        if not request.render_id.strip():
            raise SkillInputError("The skill render request must include a render ID")

        skill = self._register.get(request.skill_name)
        if not skill.is_enabled:
            raise SkillDisabledError(f"The skill {skill.name} is disabled")
        validator = _input_validator(skill)
        if validator is not None:
            try:
                error = next(validator.iter_errors(request.variables), None)
            except Unresolvable as exc:
                raise SkillConfigurationError(
                    f"The skill {skill.name} input schema contains an unresolved reference",
                    cause=exc,
                ) from exc
            except RecursionError as exc:
                raise SkillConfigurationError(
                    f"The skill {skill.name} input schema exceeds the supported validation depth",
                    cause=exc,
                ) from exc
            if error is not None:
                path = ["variables", *error.absolute_path]
                raise SkillInputError(
                    f"The skill {skill.name} input at {error.json_path} violates {error.validator}",
                    detail=json.dumps({
                        "path": path,
                        "schema_path": list(error.absolute_schema_path),
                        "constraint": error.validator,
                    }),
                )

    async def render(self, request: SkillRenderRequest) -> RenderedSkill:
        self.validate_input(request)
        skill = self._register.get(request.skill_name)
        renderer = self._register.get_renderer(skill.name)
        skill_name, render_id = request.skill_name, request.render_id

        try:
            rendered = await renderer(request)
        except (SkillInputError, SkillRenderError):
            raise
        except Exception as exc:
            raise SkillRenderError(
                f"The skill {skill.name} render failed", cause=exc
            ) from exc

        if not isinstance(rendered, RenderedSkill):
            raise SkillRenderError(f"The skill {skill.name} renderer returned an invalid result")
        if rendered.skill_name != skill_name or rendered.render_id != render_id:
            raise SkillRenderError(
                f"The skill {skill.name} renderer returned a mismatched skill name or render ID"
            )
        return rendered


def _input_validator(skill: SkillDefinition) -> Validator | None:
    schema = skill.input_schema
    if schema is None:
        return None
    try:
        # The protocol is a sentinel for unsupported explicit drafts.
        validator_class = validator_for(
            schema, default=Draft202012Validator if "$schema" not in schema else Validator,
        )
        if validator_class is Validator:
            raise SkillConfigurationError(
                f"The skill {skill.name} input schema declares an unsupported JSON Schema draft"
            )
        validator_class.check_schema(schema)
        # References may resolve within the schema, but validation must never fetch URLs.
        return validator_class(schema, registry=Registry())
    except (SchemaError, TypeError, ValueError) as exc:
        raise SkillConfigurationError(
            f"The skill {skill.name} input schema is invalid", cause=exc,
        ) from exc
