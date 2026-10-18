# Disk space report

Finds what's taking up space on a Mac (it also runs on Linux) and writes it
up as a plain-text report. It's **read-only**: it only measures and never
deletes anything.

```sh
bash disk-space/report.sh            # saves to ~/disk-report-<timestamp>.txt
bash disk-space/report.sh out.txt
```

A big home folder can take a few minutes. The report covers:

- **Disk**: free space, plus a count of Time Machine local snapshots.
- **Home folder**: the biggest folders. Any folder over 1 GB is broken
  down, up to 3 levels deep.
- **Known space hogs**: caches, Xcode build data, simulators, iPhone
  backups, Docker Desktop's disk image, package-manager caches
  (npm/pnpm/pip/conda/Cargo/Go/Gradle/...), local AI models, Downloads,
  and Trash. Each one comes with a note on how to clear it.
- **Project build folders**: `node_modules`, `.venv`/`venv`, `.next`, Rust
  `target`, `Pods`, and similar, with the date each was last modified, so
  you can find stale projects. Reinstalling recreates any of them.
- **Files over 500 MB**, **Applications** by size, and what `brew cleanup`
  and `docker system df` report.

Sizes are what's actually on disk, so iCloud/Dropbox files that are
cloud-only count as roughly zero. Anything under 50 MB is hidden.

macOS may ask whether Terminal can access Documents, Downloads, or other
apps' data. Click Allow, or give Terminal Full Disk Access in System
Settings > Privacy & Security, for a complete report. Folders it can't read
are skipped and won't appear in the report.
