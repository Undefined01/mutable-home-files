from .json_impl import JsonFormat
from .toml_impl import TomlFormat
from .yaml_impl import YamlFormat


_FORMATS = {
    "json": JsonFormat(),
    "yaml": YamlFormat(),
    "toml": TomlFormat(),
}



def get_format(name: str):
    try:
        return _FORMATS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported format: {name}") from exc
