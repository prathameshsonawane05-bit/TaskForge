# Support pathlib.Path in edit filename

Support pathlib.Path in edit filename

Would you welcome a PR to avoid this?

```
Argument of type "Path" cannot be assigned to parameter "filename" of type "str | None" in function "edit"
  Type "Path" is not assignable to type "str | None"
    "Path" is not assignable to "str"
    "Path" is not assignable to "None"Pylance[reportArgumentType](https://github.com/microsoft/pyright/blob/main/docs/configuration.md#reportArgumentType)
```

Easy workaround with:
```py
click.edit(filename=str(export_common.path))
```

but would be nice if didn't need `str`.
