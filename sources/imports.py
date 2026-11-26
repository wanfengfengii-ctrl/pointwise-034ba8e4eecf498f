from sources.catalog import AssetCatalog
from sources.pcm import validate_pcm
from workspace import transaction


def import_asset(connection, workspace_rate, source, sample_rate, samples):
    if not isinstance(source, str) or not source.strip():
        raise ValueError('source must be a non-empty label')
    try:
        source.encode('utf-8')
    except UnicodeError as error:
        raise ValueError('source must contain valid Unicode') from error
    if type(sample_rate) is not int or sample_rate != workspace_rate:
        raise ValueError('sample rate does not match the workspace')
    pcm = validate_pcm(samples)
    with transaction(connection):
        asset = AssetCatalog(connection).add(source, sample_rate, pcm)
    return asset
