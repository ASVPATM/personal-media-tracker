# Windows and Linux Native Diagnostic Capture Plan

Status: specification only; no collector script is implemented yet.

## Purpose

The packaged PMT v2.6.0 native applications pass isolated GitHub Actions packaging checks
but remain unusable on tested Windows and Linux hardware. Do not attempt another speculative
runtime fix until a diagnostic collector built from this document has captured comparable,
time-correlated evidence on both operating systems.

This plan is for a future maintainer-authored diagnostic tool that a user can run before,
during, and immediately after installing and exercising PMT. The tool must be simple,
read-only apart from its own output directory, private by default, and explicit about every
artifact it collects. It must never upload anything automatically.

## Confirmed failure signatures

### Windows native package

- Affected release confirmed by the user: v2.5.4, with the same problem reported after the
  v2.6.0 packaging changes.
- Failure occurs during native-window startup.
- The packaged WinForms/`pythonnet` path raises:
  `RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize` from the bundled
  `_internal/pythonnet/runtime/Python.Runtime.dll`.
- Investigation must distinguish a wrong DLL/runtime architecture, incompatible .NET
  runtime selection, missing native dependency, bundler layout error, or Python.NET loader
  incompatibility. CI successfully finding files is not evidence that the loader works on
  real hardware.

### Linux native package

- Affected release confirmed by the user: v2.5.4, with the same UI/crash behavior reported
  after the v2.6.0 packaging changes.
- PMT can initially open, but some pages are displaced or clipped; Settings may render near
  the bottom of the window.
- Typing into title search or interacting with affected pages can terminate the process
  with `Segmentation fault (core dumped)`.
- Investigation must correlate display server, scaling, GPU/driver, Qt/WebEngine libraries,
  rendering backend, plugin selection, sandbox state, and the last UI action. The collector
  must not assume that one software-rendering flag explains both layout and crash symptoms.

## Required user experience

The eventual download should contain one obvious launcher per platform:

- Windows: `Collect-PMT-Diagnostics.ps1`, invoked normally from PowerShell without
  administrator privileges.
- Linux: `collect-pmt-diagnostics.sh`, invoked as the logged-in desktop user without
  `sudo`.

The launchers may call a shared, bundled Python collector only if they verify that runtime
first and still report failures when Python cannot start. The collector must:

1. explain that it performs no repair, upload, installation, deletion, or configuration
   change;
2. ask for the PMT archive/executable or detect it and display the exact resolved path;
3. create a new timestamped output directory instead of overwriting an earlier run;
4. run non-interactive environment and package checks;
5. launch PMT with diagnostic logging and clearly tell the user which manual actions to
   perform;
6. let the user press Enter after each action or type `skip`, `failed`, or `quit`;
7. collect only bounded logs for the exact diagnostic time window;
8. show a plain-language summary and the path to one redacted shareable ZIP;
9. leave the original PMT installation and personal library untouched.

If a command or optional utility is unavailable, record `not available` and continue. The
collector must not download packages, enable crash reporting, modify registry/system
settings, or request elevation merely to produce a more complete report.

## Scripted reproduction sequence

Every step needs a UTC timestamp, monotonic sequence number, expected result, user-reported
result, process state, and the newest related log/crash event. The user must be able to skip
steps that cannot be reached.

1. **Baseline:** record that PMT is closed; resolve the selected package and executable.
2. **Static readiness:** run only documented non-GUI version/readiness commands that the
   selected build actually exposes. Capture exit codes and output.
3. **First launch:** start the packaged native application from the diagnostic wrapper.
4. **Initial render:** wait for the library page and record whether size and positioning are
   correct. Offer an optional screenshot with an explicit privacy warning.
5. **Settings:** open Settings and report whether the panel is centered, completely visible,
   and interactive.
6. **Search:** return to the appropriate page, focus title search, and type a synthetic title
   such as `Diagnostic Test Title`; do not use a title from the user's real library.
7. **Navigation:** visit Library and one other non-sensitive page, then return.
8. **Close:** close the window normally if it is still responsive.
9. **Crash capture:** if PMT exits unexpectedly, capture exit/signal information and only the
   crash records whose timestamps overlap this run.
10. **Second launch:** make one clean relaunch to establish whether the failure is repeatable;
    never loop automatically after a crash.

Each manual checkpoint should accept a short optional note. Notes go into the shareable
report, so the prompt must tell the user not to enter titles, usernames, tokens, or other
personal information.

## Cross-platform evidence

Collect the following with command, timestamp, duration, exit code, stdout, and stderr kept
separate:

- PMT version, diagnostic-tool version, selected package filename, size, SHA-256, and last
  modification time;
- resolved executable path and whether it came from an extracted archive, installer target,
  shortcut/launcher, or an unexpected older installation;
- a bounded tree of executable/runtime filenames, sizes, hashes, and file versions without
  copying their contents;
- OS edition/version/build, kernel, CPU architecture, executable architecture, available
  memory, locale, timezone offset, and standard display scale/resolution information;
- GPU name and driver/runtime versions using built-in system commands where possible;
- allowlisted display/runtime variables only; never dump the complete environment;
- working directory, command-line arguments generated by the collector, process ID, child
  process tree, start/end times, exit code or termination signal, and peak memory if the OS
  exposes it without invasive tooling;
- PMT logs created or changed inside the diagnostic time window, after redaction and size
  limits;
- release checksum comparison when an official `SHA256SUMS.txt` was supplied locally;
- presence and versions of required embedded UI/runtime components;
- a list of unavailable checks and why each could not run.

The diagnostic report must distinguish facts from inferences. For example, `Qt library file
present` must not be summarized as `Qt works`, and a successful process start must not be
summarized as a successful window render.

## Windows-specific evidence

Use built-in PowerShell/CIM/Event Log facilities by default. Capture:

- Windows edition, version, build, update build revision, native OS architecture, process
  architecture, and whether translation/emulation is involved;
- PowerShell version and execution policy for the current process scope only;
- installed .NET Framework release and `dotnet --list-runtimes`/`--info` when available;
- Microsoft Edge WebView2 runtime version when present, while noting that the packaged Qt
  path may not use it;
- installed Microsoft Visual C++ runtime evidence available through safe registry queries;
- GPU and signed driver versions, primary-display resolution, DPI/scaling, and multi-monitor
  arrangement;
- selected executable and bundled `python*.dll`, `Python.Runtime.dll`, CLR loader,
  Python.NET, Qt, and native dependency file versions, hashes, and PE architectures;
- file `Zone.Identifier`/Mark-of-the-Web presence and whether the archive was unblocked,
  without changing either state;
- Windows Error Reporting and Application Error events matching the PMT process and the
  run's timestamp range;
- loader errors, faulting module, exception code, and fault offset when Windows records
  them;
- whether antivirus or controlled-folder-access generated a directly relevant event in the
  bounded time window, without enumerating unrelated security history.

Do not make Process Monitor, ProcDump, Visual Studio, Dependency Walker, or Windows SDK
tools mandatory. A second opt-in advanced mode may use an already-installed ProcDump for
one crash, but memory dumps are private local artifacts and must never enter the shareable
ZIP automatically.

## Linux-specific evidence

Prefer distro-independent built-in tools, then record missing commands. Capture:

- distribution and version from `/etc/os-release`, kernel, glibc version, CPU/process
  architecture, desktop environment, session type, compositor, and X11 versus Wayland;
- monitor geometry/scaling from available non-invasive desktop tools;
- GPU, kernel driver, Mesa/OpenGL/Vulkan renderer/version evidence when the relevant tools
  already exist;
- the allowlisted variables `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE`,
  `XDG_CURRENT_DESKTOP`, `QT_QPA_PLATFORM`, `QT_SCALE_FACTOR`,
  `QTWEBENGINE_CHROMIUM_FLAGS`, and PMT-specific diagnostic variables, with usernames and
  paths redacted;
- dynamic loader results for the executable and packaged Qt/WebEngine libraries, including
  every `not found` dependency and architecture mismatch;
- packaged Qt platform plugins, image plugins, WebEngine helper/resources/locales, and
  their resolved paths and hashes;
- a separate controlled launch with `QT_DEBUG_PLUGINS=1` and bounded output, only if the
  initial launch reaches native initialization;
- stderr, termination signal, and kernel/journal messages matching the PMT PID and exact
  run window;
- `coredumpctl info` metadata for the matching process when systemd-coredump already
  captured it.

Core files, `coredumpctl dump`, and GDB memory inspection are opt-in advanced evidence.
Never copy a core into the shareable ZIP. If GDB is already installed, a separately
confirmed advanced pass may collect a thread backtrace with arguments and local variables
disabled; the report must warn that even a backtrace can reveal paths.

## Privacy and safety boundary

The collector must not read, copy, hash, summarize, or enumerate the contents of:

- the PMT SQLite database, backups, imports, exports, notes, tags, ratings, watch history,
  artwork cache, or media titles;
- PMT configuration values, API tokens, cookies, passwords, OS credential stores, browser
  profiles, SSH keys, or complete environment-variable output;
- unrelated application logs, Event Log entries, journal entries, processes, or network
  activity outside the diagnostic time window;
- screenshots, memory dumps, or core dumps without a separate explicit confirmation.

Redaction must occur before files enter the shareable directory. Replace home directories,
usernames, hostnames, private/tailnet addresses, email addresses, invitation/session values,
query strings, bearer tokens, and token-like high-entropy values with stable placeholders.
Preserve enough consistency to correlate the same path or host across files. Truncate each
command output and log using documented per-file and total-size limits, marking truncation.

The final screen must say exactly what was collected, what was excluded, and that the user
should still inspect every file before sharing it.

## Required output layout

The eventual collector should produce this deterministic shape:

```text
pmt-diagnostics-<windows|linux>-<UTC timestamp>/
├── SHARE_THIS/
│   ├── SUMMARY.md
│   ├── manifest.json
│   ├── reproduction.json
│   ├── commands.jsonl
│   ├── system/
│   ├── package/
│   ├── launch/
│   ├── crash-metadata/
│   ├── redaction-report.json
│   └── SHA256SUMS.txt
├── PRIVATE_DO_NOT_SHARE/
│   └── README.txt
└── pmt-diagnostics-<platform>-<timestamp>-SHARE_THIS.zip
```

`manifest.json` must carry a schema version, collector version/commit, PMT version, OS,
start/end timestamps, completed/skipped/failed checks, redaction counts, and SHA-256 for
every shareable file. `SUMMARY.md` should put the failure stage, exit status, matching crash
metadata, and missing dependencies first. `PRIVATE_DO_NOT_SHARE` must remain empty unless
the user separately opts into an advanced dump; it exists to prevent private artifacts from
being confused with the ZIP intended for an issue.

## Acceptance tests for the future collector

Do not ask users to run the script until all of these pass in clean Windows and Linux test
environments:

1. Running without elevation creates a report even when PMT cannot start.
2. Paths containing spaces and non-ASCII characters work.
3. Selecting the wrong executable produces a clear error without probing unrelated files.
4. Missing PowerShell utilities, .NET, `ldd`, journal access, or graphics tools are reported
   rather than causing the collector to stop.
5. A timeout terminates only the PMT process tree started by the collector.
6. Ctrl+C preserves a valid partial report and does not leave PMT or tracing processes.
7. Two runs never overwrite one another.
8. Automated fixtures prove redaction of home paths, emails, IPv4/IPv6, Tailscale names,
   URLs, query strings, authorization headers, API-token patterns, and high-entropy secrets.
9. Tests prove that databases, config values, artwork, exports, and complete environment
   dumps cannot enter `SHARE_THIS`.
10. Output size caps and truncation markers work on very large logs.
11. The ZIP checksum matches and every manifest hash validates after extraction.
12. Windows testing captures the Python.NET loader failure without requiring the GUI to
    initialize.
13. Linux testing captures a SIGSEGV and matching journal/coredump metadata without placing
    a core in the shareable archive.
14. A successful control run is clearly distinguished from `not reproduced` and from a
    skipped manual step.

## Evidence review and next decision

When reports are returned, compare at least one failing Windows run, one failing Linux run,
and one successful macOS/CI control at these boundaries:

1. package contents and executable architecture;
2. runtime/native dependency resolution;
3. native-window backend initialization;
4. first complete layout;
5. the exact Settings/search event;
6. crash module, signal/exception, and final process logs.

Only then create narrowly scoped fixes. Windows and Linux should remain marked unsupported
until their respective package launches, completes the scripted reproduction sequence on
real hardware, restarts cleanly, and passes a second independent-machine smoke test. A
green packaging runner alone must not remove the warning.
