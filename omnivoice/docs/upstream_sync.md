# Upstream sync procedure

`omnivoice_core/` is a *vendored snapshot* of the inference subset of
[k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice). It is never
edited in place. To pull a newer upstream commit:

1. **Pin the upstream ref.** Decide which upstream `git` ref (tag /
   commit) you are syncing to. Record it at the top of the PR
   description.

2. **Re-run the vendoring script** (manual; we intentionally do not
   automate this so changes get human review):

   ```bash
   # from a clone of upstream
   SRC=$(pwd)/omnivoice                         # upstream omnivoice/ pkg
   DST=/path/to/Geny/omnivoice/omnivoice_core
   rm -rf "$DST"/{models,utils}
   mkdir -p "$DST"/{models,utils}
   cp "$SRC/models/__init__.py"   "$DST/models/"
   cp "$SRC/models/omnivoice.py"  "$DST/models/"
   cp "$SRC/utils/__init__.py"    "$DST/utils/"
   cp "$SRC/utils/audio.py"       "$DST/utils/"
   cp "$SRC/utils/common.py"      "$DST/utils/"
   cp "$SRC/utils/duration.py"    "$DST/utils/"
   cp "$SRC/utils/lang_map.py"    "$DST/utils/"
   cp "$SRC/utils/text.py"        "$DST/utils/"
   cp "$SRC/utils/voice_design.py" "$DST/utils/"
   find "$DST" -name '*.py' -exec sed -i \
       -e 's/from omnivoice\.utils/from omnivoice_core.utils/g' \
       -e 's/from omnivoice\.models/from omnivoice_core.models/g' \
       -e 's/import omnivoice\.utils/import omnivoice_core.utils/g' \
       -e 's/import omnivoice\.models/import omnivoice_core.models/g' {} +
   ```

3. **Verify imports.** The only legitimate post-sed references to the
   bare word `omnivoice` should be:

   - The docstring mention of `omnivoice.training.builder`.
   - `model_type = "omnivoice"` (HuggingFace model registry id — must
     stay as the upstream string).
   - `AutoConfig.register("omnivoice", OmniVoiceConfig)`.

   ```bash
   grep -RnE "(^|[^_a-zA-Z])omnivoice([^_a-zA-Z]|$)" omnivoice_core/
   ```

4. **Diff the new utils against existing API surface.** If new utility
   functions appear or signatures change, decide whether `server/`
   needs updates.

5. **Smoke test.**

   ```bash
   pip install -e Geny/omnivoice
   python -c "from omnivoice_core import OmniVoice; print(OmniVoice)"
   pytest Geny/omnivoice/tests
   ```

6. **Document.** Update `Geny/dev_docs/<cycle>/progress/` with the
   upstream ref and a one-line summary of any behavioural deltas.

## What we deliberately don't vendor

- `omnivoice/cli/`     — replaced by `server/`
- `omnivoice/data/`    — training-only
- `omnivoice/training/`— training-only
- `omnivoice/eval/`    — evaluation tooling
- `omnivoice/scripts/` — data-prep helpers
- `omnivoice/examples/` — recipes

If you ever need fine-tuning, do it in a *separate* clone of upstream
and import the resulting checkpoint via `OMNIVOICE_MODEL`.
