# Image Generation and Editing

The first image generation adapter uses the OpenAI-compatible Images API.
Configure an enabled `openai` provider with its API key and optional base URL,
then open `/images.html` from the chat sidebar or settings. Model IDs may be
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
opened from history. Blank names use `evernight-image-<number>`; PNG, JPEG and
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

Image requests disable automatic SDK retries. Cancelling browser waiting does
not guarantee upstream cancellation and may still incur charges. Streaming generation, masks and agent image tools are
outside this interface.

## Upload and Edit

On `/images.html`, choose **上传改图**, select reference images and a model,
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
