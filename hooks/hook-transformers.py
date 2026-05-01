from PyInstaller.utils.hooks import copy_metadata, get_module_attribute, is_module_satisfies, logger


datas = []

try:
    dependency_table = get_module_attribute(
        'transformers.dependency_versions_table',
        'deps',
    )
except Exception:
    logger.warning(
        'hook-transformers: failed to query dependency table',
        exc_info=True,
    )
    dependency_table = {}

for dependency_name, dependency_req in dependency_table.items():
    if not is_module_satisfies(dependency_req):
        continue
    try:
        datas += copy_metadata(dependency_name)
    except Exception:
        pass


# Keep transformers importable without shipping source .py files for the
# entire model zoo; the Cohere runtime only needs bytecode at inference time.
module_collection_mode = 'pyz'

# Legacy model families deliberately excluded from the packaged runtime.
excludedimports = [
    'transformers.models.whisper',
    'transformers.models.whisper.configuration_whisper',
    'transformers.models.whisper.feature_extraction_whisper',
    'transformers.models.whisper.generation_whisper',
    'transformers.models.whisper.modeling_whisper',
    'transformers.models.whisper.processing_whisper',
    'transformers.models.whisper.tokenization_whisper',
    'transformers.models.nemotron',
    'transformers.models.nemotron.configuration_nemotron',
    'transformers.models.nemotron.modeling_nemotron',
    'transformers.models.nemotron_h',
    'transformers.models.nemotron_h.configuration_nemotron_h',
    'transformers.models.nemotron_h.modeling_nemotron_h',
    'transformers.models.granite',
    'transformers.models.granite.configuration_granite',
    'transformers.models.granite.modeling_granite',
    'transformers.models.granite_speech',
    'transformers.models.granite_speech.configuration_granite_speech',
    'transformers.models.granite_speech.feature_extraction_granite_speech',
    'transformers.models.granite_speech.modeling_granite_speech',
    'transformers.models.granite_speech.processing_granite_speech',
    'transformers.models.granitemoe',
    'transformers.models.granitemoe.configuration_granitemoe',
    'transformers.models.granitemoe.modeling_granitemoe',
    'transformers.models.granitemoehybrid',
    'transformers.models.granitemoehybrid.configuration_granitemoehybrid',
    'transformers.models.granitemoehybrid.modeling_granitemoehybrid',
    'transformers.models.granitemoeshared',
    'transformers.models.granitemoeshared.configuration_granitemoeshared',
    'transformers.models.granitemoeshared.modeling_granitemoeshared',
]