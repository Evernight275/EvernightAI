# Image Generation and Editing

The first image generation adapter uses the OpenAI-compatible Images API.
Configure an enabled `openai` provider with its API key and optional base URL,
then open **图像生成** in the chat sidebar (`/chat.html#images`). Model IDs may be
entered manually; remote `/models` discovery is not required. Declared models
with explicit capabilities must include `image_generation`.

## HTTP

`POST /images/generations` requires `images:generate` when authorization is
enabled. Existing authentication headers apply.

```json
{
  "provider_id": "main",
  "request": {
    "model_id": "gpt-image-1",
    "prompt": "A green leaf on a white background",
    "count": 1,
    "timeout_seconds": 180
  }
}
```

Optional fields: `size`, `quality`, `output_format` (`png`, `jpeg`, `webp`),
`background` (`auto`, `transparent`, `opaque`), `result_format` (`url`, `base64`).
Omitted fields use provider defaults. Availability and supported values depend
on the chosen model. GPT Image models return Base64 and reject URL output.

The response includes `model_id`, `images`, optional `created` and `usage`.
Each image contains `url` or `base64_data` with `mime_type`, plus an optional
`revised_prompt`. Supported bitmap formats are PNG, JPEG and WebP. Unknown
usage counts stay unavailable; raw provider usage remains in metadata.

Generation through the assembled interface saves a record containing the request
and original result before attempting URL archival. SQLite runtimes retain these
records across restarts; memory runtimes retain them for their lifetime. Base64
images are stored with the record. URL images are downloaded into Base64 when
possible, so the saved preview and download no longer depend on expiring links.
The initial URL record remains available if archival is interrupted.

The frontend's history view can restore saved results and request parameters
without making another provider call. Records survive provider deletion. The
history list contains summaries only, with the original image data loaded on
detail access. Records and images are deleted together; an archival completion
cannot recreate a deleted record.

Each preview has an editable download filename. This also applies to images
opened from history. Default and blank names use
`evernight-image-<number>_<YYYYMMDD>_<HHmmss>_<SSS>` in the browser's local time;
custom names are preserved. PNG, JPEG and
WebP extensions follow the downloaded bitmap's actual format. Download naming
is local to the current preview and does not change the saved generation record.

### History API

| Endpoint | Permission | Result |
| --- | --- | --- |
| `GET /images/records?limit=20&cursor=...` | `images:list` | Summary page, newest first |
| `GET /images/records/{record_id}` | `images:get` | Saved request and images |
| `DELETE /images/records/{record_id}` | `images:delete` | 204 after deletion |

Authenticated access is restricted to the current principal's records, including
generation ownership. Requests cannot override that ownership. Cross-owner
detail and delete requests return 404. Image API responses use `Cache-Control:
no-store`; identity changes discard pending browser reads and clear drafts and
previews. Without authentication, history follows the runtime's local shared
access model.

Successful generation responses include `record_id`. Optional
`persistence_warning` indicates `archive_incomplete`, `save_failed`, or
`record_deleted`. Persistence failures still return the generated images and
never automatically repeat a potentially paid model request. `record_deleted`
means another request deleted the record while archival was in progress.

Remote archival uses verified public IP addresses, preserves the original HTTP
Host and TLS identity, rejects credential URLs and HTTPS downgrades, and validates
every redirect. It sends no provider credentials or cookies. Limits are 20 MB per
remote image, 50 MB of downloaded data per response, three redirects, and 30
seconds total. When system DNS returns only proxy Fake-IP addresses in
`198.18.0.0/15` or `2001:2::/48`, archival resolves the hostname through
[Cloudflare DNS over HTTPS](https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/)
at `https://1.1.1.1/dns-query`. The resulting addresses still undergo public-IP
validation and connection pinning. Literal IP URLs and other private DNS
destinations remain blocked; a failed fallback preserves the URL and warning.
Content must be PNG, JPEG, or WebP. Inaccessible, private, oversized
or unsupported URL results remain saved as references with a warning. Their
remote links may expire, so download them promptly. Cross-origin browser
download restrictions may require opening the original URL to save it.

Image requests disable automatic SDK retries. Cancelling browser waiting leaves
the background task running. Streaming provider progress is outside this interface.

## Background Tasks

The image page submits `POST /images/tasks`. The server
returns **202** with a task summary and `Location: /images/tasks/{task_id}` before
calling the provider. Browsers poll saved status; refreshing
or leaving the page never cancels or resubmits an accepted task.

```json
{
  "task_id": "0123456789abcdef0123456789abcdef",
  "provider_id": "main",
  "request": { "model_id": "your-image-model", "prompt": "A green leaf" },
  "session_id": "optional-existing-session"
}
```

`request` accepts generation parameters or the same ordered edit references and
optional mask described below. `task_id` is an optional 32-character lowercase
hexadecimal ID; the server allocates one when omitted. Repeat the same ID,
principal, provider, request and session to retrieve the existing task, including
after a lost response. Reusing an ID for a different request returns 409. The UI
retains the ID when the initial submission response is lost.

| Endpoint | Permission | Result |
| --- | --- | --- |
| `POST /images/tasks` | `images:generate` | 202 task summary |
| `GET /images/tasks?limit=20&cursor=...&session_id=...` | `images:list` | Summary page, newest first |
| `GET /images/tasks/{task_id}` | `images:get` | Saved status and optional result record ID |

Tasks use `queued`, `running`, `succeeded`, `failed`, and `interrupted`. Status
reads contain no reference or mask Base64. A successful task's `record_id` can
be read through the existing history API. Ownership and `no-store` rules also
apply to tasks; cross-owner IDs return 404. An optional session association
requires `sessions:get` and an existing session owned by the principal.

SQLite retains task inputs, session association, status and results across
restarts. Queued tasks resume after provider restoration. Workers claim each
task atomically and renew a 30-second lease every 10 seconds; expired running
tasks become interrupted instead of automatically replaying a potentially paid
request. Graceful shutdown also marks running work interrupted. A result saved
before interrupted URL archival remains accessible through the task and history.
Two tasks execute concurrently per process, with at most ten unfinished tasks
per principal. Memory runtimes retain tasks only for their lifetime. Deleting a
result history record also deletes its associated task inputs and mask.

The synchronous `/images/generations` and `/images/edits` endpoints remain
available. Background tasks require a saved result to report success; persistence
failures report failure and do not repeat the provider call.

## Image Tool in Chat

The assembled interface registers `generate_image` in the tool catalog. Ask in
chat, for example “帮我生成一张海边日落” and then “把刚才的天空改成紫色”. The
chat model chooses the tool; approve its execution in the existing tool card.
Images appear in that card, support a custom download filename, and are restored
from saved tool traces when the session is reopened. There is no separate image
composer or dialog inside chat.

The tool accepts `prompt`, optional `provider_id`, `model_id`, `count`, `size`,
`quality`, `output_format`, `timeout_seconds`, and up to 16 ordered `references`
with `record_id` and `image_index` (zero-based). With no references it generates;
with references it edits archived images after checking ownership. Without explicit model choices,
editing keeps the referenced image's provider/model, and generation selects the
first enabled OpenAI-compatible provider's declared `image_generation` model.
Configure that capability in provider settings; chat keeps its own model.

New image tool calls request `quality: high` and `output_format: png` by default.
Explicit values override these defaults; `null` uses the provider's default.
Providers may return a different format or resolution. Archival and download
preserve the returned bytes, without resizing or re-encoding. Replaying an
existing task keeps its original omitted quality, format and timeout values.

The image tool defaults to a 180-second request timeout, independently of the
model's configured timeout. Set `timeout_seconds` to a positive number up to 600
for slower generation or editing. Failed tool calls preserve the image task's
error type and message in the chat trace and execution record.

Tool calls reuse background tasks and history storage. The agent supplies trusted
owner, session, run and call identity; models cannot set those execution fields.
The tool requires approval and records an idempotency key so replay retrieves the
same task instead of repeating generation. It returns saved record references to
the model, without image Base64; the browser reads images through the authenticated
history API. Cancelling the chat wait leaves accepted image work running, and its
status and result remain available on the image page.

## Upload and Edit

In the image workspace (`/chat.html#images`), choose **上传改图**, select reference images and a model,
and describe the desired changes. Select several images at once or append more
in later batches. Each preview shows its current number. Images can be removed
or moved forward/backward; refer to them as "图 1", "图 2", etc. in the prompt.
The submitted list follows exactly the displayed order.

The project accepts 1–16 PNG, JPEG or WebP references, with a 20 MiB per-image
limit and a 50 MiB total decoded-input limit. Empty, unsupported or unreadable
files are rejected before submission. Uploads detect the actual bitmap signature
instead of trusting the filename or browser-reported MIME type. A JPEG or WebP
named `.png` is sent using its actual type without modifying its bytes. An invalid batch adds no images and keeps
existing selections. Uploading temporarily disables submission and reference
changes. The model and service must support multiple images via the
[OpenAI-compatible image edit endpoint](https://developers.openai.com/api/reference/resources/images/methods/edit).
Model discovery is not required; unsupported upstream requests surface the
provider error and are not retried automatically.

`POST /images/edits` uses the same authentication and `images:generate` permission
as text generation. Its JSON body adds a required ordered `images` list to the
normal request:

```json
{
  "provider_id": "main",
  "request": {
    "model_id": "gpt-image-2.5-sunburst",
    "prompt": "Combine the leaf from image 1 with the background from image 2",
    "images": [
      { "base64_data": "<first reference encoded as Base64>", "mime_type": "image/png" },
      { "base64_data": "<second reference encoded as Base64>", "mime_type": "image/jpeg" }
    ]
  }
}
```

The previous single `image` field is still accepted and normalized into an
`images` list, including when reading existing saved records. Providing both
fields is rejected. History responses and new records use `images`.

The backend validates Base64, per-image and total decoded size, image count and
bitmap signature against the supplied MIME type, then uploads the bytes to the
provider as multipart form data. A single reference uses `image`; multiple
references use ordered `image[]` file parts. Remote URLs, local filesystem paths
and caller-provided filenames are not accepted as input. Results have the same
response shape, archival and custom download naming behavior as text generation.

All reference images are saved with the edit request and result. Opening its
history record restores the complete ordered reference list and editing
parameters without another provider call; deleting the record removes references
and result. Ownership checks apply to every saved reference. Upload contents are
cleared on identity changes, page closure and switching to text generation.
Validation responses omit submitted image data.

## Partial Editing

After uploading references, enable **局部涂抹修改图 1**. Paint the area to change,
adjust brush size, restore selected areas or clear the selection, then enter the
edit instruction. The mask always applies to the first reference; moving or
replacing that reference clears its selection. History restores a saved mask.

The browser converts the first reference to PNG only when submitting a masked
edit. It preserves the original dimensions and sends a matching PNG mask with
transparent pixels for selected areas and opaque pixels elsewhere. Other
references retain their original bytes and format. The backend requires a PNG
mask with an alpha channel matching the first PNG reference's dimensions, up to
32 million pixels and 20 MiB. References plus mask must fit the 50 MiB decoded
input limit. An empty browser selection does not submit a task.

Add an optional `mask` to the edit request:

```json
"mask": { "base64_data": "<PNG mask encoded as Base64>", "mime_type": "image/png" }
```

The adapter uploads the mask as a real multipart `mask` file alongside the
ordered references. The selected provider/model must support masks. Masks guide
the model and do not guarantee an exact pixel boundary; see the official
[image editing guide](https://developers.openai.com/api/docs/guides/image-generation).

## Opt-in Real Test

Normal tests use local fakes. This explicitly enabled smoke test submits one
image request and may incur charges:

```powershell
$env:EVERNIGHTAI_RUN_REAL_IMAGES="1"
$env:EVERNIGHTAI_REAL_IMAGES_API_KEY="your-key"
$env:EVERNIGHTAI_REAL_IMAGES_MODEL="your-image-model"
# Optional for an OpenAI-compatible endpoint:
$env:EVERNIGHTAI_REAL_IMAGES_BASE_URL="https://your-endpoint/v1"
.\.venv\Scripts\python.exe -m pytest tests\test_real_image_generation.py -m real_images
```

`OPENAI_API_KEY` and `OPENAI_BASE_URL` are supported as fallbacks. Provider
unavailability skips the smoke test with a reason.
