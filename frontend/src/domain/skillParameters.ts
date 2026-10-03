export type ParameterField = {
  name: string;
  schema: Record<string, unknown>;
  type: 'string' | 'number' | 'integer' | 'boolean';
  required: boolean;
};

export function parameterFields(schema?: Record<string, unknown> | null): ParameterField[] | null {
  if (
    !schema ||
    schema.type !== 'object' ||
    !schema.properties ||
    typeof schema.properties !== 'object' ||
    Array.isArray(schema.properties)
  )
    return null;
  const rootKeys = [
    'type',
    'properties',
    'required',
    'additionalProperties',
    'title',
    'description',
    '$schema',
  ];
  if (Object.keys(schema).some((key) => !rootKeys.includes(key))) return null;
  const required = Array.isArray(schema.required) ? schema.required : [];
  const fields: ParameterField[] = [];
  for (const [name, value] of Object.entries(schema.properties)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const property = value as Record<string, unknown>;
    const type = property.type;
    if (type !== 'string' && type !== 'number' && type !== 'integer' && type !== 'boolean')
      return null;
    const keys = [
      'type',
      'enum',
      'title',
      'description',
      'default',
      'minimum',
      'maximum',
      'minLength',
      'maxLength',
      'pattern',
      'format',
    ];
    if (Object.keys(property).some((key) => !keys.includes(key))) return null;
    if (
      property.enum &&
      (!Array.isArray(property.enum) ||
        property.enum.some((item) => item !== null && typeof item === 'object'))
    )
      return null;
    fields.push({ name, schema: property, type, required: required.includes(name) });
  }
  return fields;
}

export function parseSkillVariables(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
    throw new Error('技能参数必须是 JSON 对象');
  return parsed as Record<string, unknown>;
}
