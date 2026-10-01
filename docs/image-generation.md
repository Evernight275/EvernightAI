# Image Generation

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
seconds total. Content must be PNG, JPEG, or WebP. Inaccessible, private, oversized
or unsupported URL results remain saved as references with a warning. Their
remote links may expire, so download them promptly. Cross-origin browser
download restrictions may require opening the original URL to save it.

Image requests disable automatic SDK retries. Cancelling browser waiting does
not guarantee upstream cancellation and may still incur charges. Image editing,
streaming generation and agent image tools are outside this initial interface.

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
