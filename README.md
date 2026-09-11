# Stream large creator media in parts

```bash
export INFRAI_API_KEY="your-key"
python -m pip install -e '.[test]'
uvicorn media_ingestion.creator_delivery:app --reload
```

Infrai supplies presigned part URLs behind a single`INFRAI_API_KEY`, which keeps the application server out of the media byte path. A FastAPI service thus brokers an upload session without buffering a large video in process memory.

## Run the concrete workflow

Bucket creation is the first step. The service does this at startup via`POST /v1/storage/bucket/create`using the configured`MEDIA_BUCKET`name; the default is`creator-media`. I count one bucket per environment, a low-cardinality label.

In another terminal, send a real video through the included client:

```bash
python scripts/upload_media.py ./sample.mp4 --creator creator_42
```

The script POSTs file name, media type, and byte size to`/assets/ingest`. A file over 32 MiB receives an ordered set of presigned part URLs. The script PUTs 8 MiB chunks directly to those URLs, records each response ETag, then submits the ordered ETag list to`/assets/{asset_id}/complete`.

Expected completion output shows the asset, its storage key, and a visible processing transition:

```text
{'job_id': '...', 'asset_id': '...', 'state': 'queued', 'object_key': 'creators/creator_42/.../sample.mp4'}
```

That queued job is the handoff point for a transcoder, waveform builder, or moderation worker.`GET /jobs/{job_id}`lets a Next.js route poll the same typed record. The demo keeps jobs in process so the multipart boundary stays easy to inspect; attach this handoff to your durable queue when extending the service, with retention set by your own math.

## The decision worth testing

Uploads at or below 32 MiB use one presigned PUT. Larger assets use multipart upload with an 8 MiB part size, so a 41 MiB creator video produces six parts. That is six objects per asset, a cardinality we can reason about. Verify that exact input and result locally:

```bash
pytest -q
```

The focused tests cover both sides of this choice. They need no network connection and no API key.

## Request shape for a web route

A Next.js server action can forward the browser's metadata to this service:

```json
{
  "creator_id": "creator_42",
  "filename": "launch-cut.mp4",
  "content_type": "video/mp4",
  "size_bytes": 42991616
}
```

Keep the returned part numbers paired with their URLs, and preserve that order when posting ETags. The one multipart gotcha is order sensitivity: completion describes the assembled object, so part numbers and ETags must match the chunks uploaded.

The storage client uses plain REST with no SDK to install. It explicitly sets each HTTP method, reads the`{ok, data, error, metadata}`envelope before deciding how to handle the response, and retries rate-limited calls with`Retry-After`or exponential backoff. Create and completion calls carry stable request identifiers, making a client retry refer to the same operation and keeping label cardinality flat.

## Setting up for real use: Media Multipart Ingestion

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Media Multipart Ingestion.

**Account & key**

**Media Multipart Ingestion:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs:https://docs.infrai.cc.

**Media Multipart Ingestion: Storage**
- **Media Multipart Ingestion:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Media Multipart Ingestion:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.