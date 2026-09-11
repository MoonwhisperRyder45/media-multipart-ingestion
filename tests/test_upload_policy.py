from media_ingestion.upload_policy import MIN_MULTIPART_PART_BYTES, plan_upload


def test_large_creator_video_is_split_into_expected_parts() -> None:
    size_bytes = 41 * 1024 * 1024

    plan = plan_upload(size_bytes)

    assert plan.mode == "multipart"
    assert plan.part_size == MIN_MULTIPART_PART_BYTES
    assert plan.part_count == 6


def test_small_audio_uses_one_direct_upload() -> None:
    plan = plan_upload(12 * 1024 * 1024)

    assert plan.mode == "single"
    assert plan.part_count == 1
