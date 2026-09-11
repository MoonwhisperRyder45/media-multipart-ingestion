import argparse
import mimetypes
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload one media file through the ingestion service")
    parser.add_argument("file", type=Path)
    parser.add_argument("--creator", required=True)
    parser.add_argument("--service", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    content_type = mimetypes.guess_type(args.file.name)[0] or "video/mp4"
    with httpx.Client(timeout=120.0) as client:
        start = client.post(
            f"{args.service}/assets/ingest",
            json={
                "creator_id": args.creator,
                "filename": args.file.name,
                "content_type": content_type,
                "size_bytes": args.file.stat().st_size,
            },
        )
        start.raise_for_status()
        session = start.json()

        if session["mode"] == "single":
            with args.file.open("rb") as media:
                uploaded = client.put(session["upload_url"], content=media)
                uploaded.raise_for_status()
            print({"asset_id": session["asset_id"], "state": "uploaded"})
            return

        completed_parts = []
        with args.file.open("rb") as media:
            for part in session["parts"]:
                chunk = media.read(session["part_size"])
                uploaded = client.put(part["upload_url"], content=chunk)
                uploaded.raise_for_status()
                completed_parts.append(
                    {"part_number": part["part_number"], "etag": uploaded.headers["ETag"]}
                )

        completed = client.post(
            f"{args.service}/assets/{session['asset_id']}/complete",
            json={"upload_id": session["upload_id"], "parts": completed_parts},
        )
        completed.raise_for_status()
        print(completed.json())


if __name__ == "__main__":
    main()
