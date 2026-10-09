# Asset Sizes

## Basic Sizes

```{versionchanged} 1.19.0
Multiple `--size` parameters can be specified
```

Each asset in iCloud may have multiple sizes available for downloading:
- original
- medium
- thumb

Size can be selected with the `--size` parameter and multiple specifications are accepted (e.g., `--size original --size medium`). The default is `original`.

Regular video sizes can be selected independently with the repeatable
`--size-video` parameter (currently `original`, `medium`, or `thumb`). When
`--size-video` is omitted, `--size` continues to control both images and
regular videos. When it is supplied, `--size` controls images and
`--size-video` controls regular videos. Live Photo MOVs remain controlled by
`--live-photo-size`.

The `original` and `medium` video versions are generally available. Individual
iCloud assets may not provide every requested version.

If a requested image or video size is not available for the asset in iCloud,
then `original` is downloaded and a warning is logged, unless `--force-size`
is specified. With `--force-size`, the unavailable requested version is
skipped and the condition is logged instead; the overall download does not
fail.

Assets for sizes other than original will have a suffix added to their name, e.g., `IMG-1234-medium.JPG`.

## Special Sizes

```{versionadded} 1.19.0
```

Image edits are represented as a special size `adjusted`. Two common use cases related to edits:
- Download the edited version or original if it was not edited: use the `--size adjusted` parameter
- Download edit and original: use the `--size adjusted --size original` parameters. Edits will have a `-adjusted` suffix added if the file extension is the same as the original.

```{note}
Portraits are represented in iCloud as edits.
```

```{seealso}
[RAW](raw) assets use `alternative` size
```
