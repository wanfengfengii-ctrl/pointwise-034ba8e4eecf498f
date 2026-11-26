from cuts.revisions import RevisionStore
from releases.cues import build_cue_sheet
from releases.eligibility import require_same_revision_confirmation
from releases.packages import PackageStore
from render.wave import encode_wave
from workspace import transaction


class UnknownReleaseRevision(LookupError):
    pass


def issue_release(connection, renderer, sample_rate, revision_id, confirmation_id):
    with transaction(connection):
        revision = RevisionStore(connection).get(revision_id)
        if revision is None:
            raise UnknownReleaseRevision('unknown revision')
        confirmation = require_same_revision_confirmation(connection, revision, confirmation_id)
        samples = renderer.render_strict(revision, 0, revision.total_frames)
        wav = encode_wave(samples, sample_rate)
        cue_sheet = build_cue_sheet(revision, sample_rate)
        package = PackageStore(connection).insert_package(
            revision.revision_id, confirmation.confirmation_id, cue_sheet, wav
        )
    return package
