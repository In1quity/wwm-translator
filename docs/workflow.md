# Workflow

## Translator workflow (GUI)

1. Start `WWMTranslator.exe`.
2. Use **Project -> Create DB**.
3. Select game root folder and target language.
4. Wait for extraction progress if this is a new/empty project.
5. Optionally use **Project -> Load master translation**.
6. Optionally use **Project -> Load glossary**.
7. Translate strings, use per-row **Approve/Reject**, and click **Save translation**.
8. Use **Translation -> Save master translation** to apply approved rows into master.
9. Use **Tools -> Run QA** if needed.
10. Use **Export -> Export translation**.

## File lifecycle

- Game input source: selected game folder (`Package/...`, `LocalData/...`).
- Working DB: `data/projects/<slug>_<lang>/project.db`.
- User translation: `data/projects/<slug>_<lang>/my_translation.tsv`.
- Output: selected export directory + zip package.

## CI workflow

Defined in `.github/workflows/ci.yml`.

- On push/pull_request:
  - install dependencies
  - run `ruff`
  - run `pytest`
- On tag `v*`:
  - run Windows build (`packaging/build_exe.ps1`)
  - create `WWMTranslator-v<tag>-win64.zip`
  - upload zip asset to GitHub Release
