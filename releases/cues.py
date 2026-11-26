def build_cue_sheet(revision, sample_rate):
    return {
        'revision_id': revision.revision_id,
        'project_id': revision.project_id,
        'sample_rate': sample_rate,
        'total_frames': revision.total_frames,
        'segments': revision.describe_segments(),
    }
