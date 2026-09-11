from dataclasses import dataclass
from math import ceil

MIN_MULTIPART_PART_BYTES = 8 * 1024 * 1024
MULTIPART_THRESHOLD_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class UploadPlan:
    mode: str
    part_size: int
    part_count: int


def plan_upload(size_bytes: int) -> UploadPlan:
    if size_bytes <= 0:
        raise ValueError("size_bytes must be positive")
    if size_bytes <= MULTIPART_THRESHOLD_BYTES:
        return UploadPlan(mode="single", part_size=size_bytes, part_count=1)

    part_count = ceil(size_bytes / MIN_MULTIPART_PART_BYTES)
    return UploadPlan(
        mode="multipart",
        part_size=MIN_MULTIPART_PART_BYTES,
        part_count=part_count,
    )
