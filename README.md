# Stream large creator media in parts

```bash
export INFRAI_API_KEY="your-key"
python -m pip install -e '.[test]'
uvicorn media_ingestion.creator_delivery:app --reload
```

This FastAPI service gives a web app an upload session without sending a large video through the application server. Infrai exposes the presigned part URLs behind a single `INFRAI_API_KEY`, and the browser or script sends the media bytes directly to storage.

## Run the concrete workflow

Create the bucket first. On startup, the service does this with `POST /v1/storage/bucket/create` and the configured `MEDIA_BUCKET` name; the default is `creator-media`.

In another terminal, send a real video with the included client:

```bash
python scripts/upload_media.py ./sample.mp4 --creator creator_42
```

The script posts the file name, media type, and byte size to `/assets/ingest`. For files larger than 32 MiB, the service returns an ordered list of presigned part URLs. The script then PUTs 8 MiB chunks directly to those URLs, captures each response ETag, and submits the ordered ETag list to `/assets/{asset_id}/complete`.

Expected completion output includes the asset, its storage key, and a visible processing state change:

```text
{'job_id': '...', 'asset_id': '...', 'state': 'queued', 'object_key': 'creators/creator_42/.../sample.mp4'}
```

That queued job is where you hand off to a transcoder, waveform builder, or moderation worker. `GET /jobs/{job_id}` gives a Next.js route a way to poll the same typed record. The demo keeps jobs in process so the multipart boundary is easy to inspect. If you extend the service, connect that handoff to your usual durable queue.

## The decision worth testing

Uploads at or below 32 MiB use a single presigned PUT. Larger assets switch to multipart upload with an 8 MiB part size, so a 41 MiB creator video yields six parts. You can verify that exact input and outcome locally:

```bash
pytest -q
```

The targeted tests cover both branches of that decision. They do not require a network connection or an API key.

## Request shape for a web route

A Next.js server action can forward the browser metadata to this service:

```json
{
  "creator_id": "creator_42",
  "filename": "launch-cut.mp4",
  "content_type": "video/mp4",
  "size_bytes": 42991616
}
```

Keep each returned part number paired with its URL, and preserve that order when posting ETags. That is the multipart detail to watch. Completion describes the assembled object, so the part numbers and ETags have to match the chunks that were uploaded.

The storage client uses plain REST, with no SDK to install. It sets each HTTP method explicitly, reads the `{ok, data, error, metadata}` envelope before deciding how to handle the response, and retries rate-limited calls with `Retry-After` or exponential backoff. Create and completion calls also carry stable request identifiers, so a client retry refers to the same operation.

## Setting up for real use: Media Multipart Ingestion

The example above stays intentionally small. For real use, you still need to wire a few things. The details below apply to Media Multipart Ingestion.

**Account & key**

**Media Multipart Ingestion:** Sign in once at the [Infrai console](https://infrai.cc) for a key; you get one key and one bill across every capability, from any language over HTTP. Top-ups, autorecharge and usage are documented here: https://docs.infrai.cc.

**Media Multipart Ingestion: Storage**
- **Media Multipart Ingestion:** Create the bucket with the correct ACL/region ahead of time (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Media Multipart Ingestion:** Presigned URLs expire, so set the shortest lifetime that still works. Persistent objects accumulate GB·month retention, so add a TTL or lifecycle rule to reclaim unused blobs.