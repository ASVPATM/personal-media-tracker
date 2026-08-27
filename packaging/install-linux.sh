#!/bin/sh
set -eu

app_name="personal-media-tracker"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
install_dir="$data_home/$app_name"
applications_dir="$data_home/applications"
desktop_file="$applications_dir/$app_name.desktop"
version_file="$script_dir/PMT_BUNDLE_VERSION"

if [ "$(id -u)" -eq 0 ]; then
  printf '%s\n' "Do not install the Personal Media Tracker desktop app with sudo or as root." >&2
  printf '%s\n' "Run ./install-linux.sh as the normal desktop user who will use PMT." >&2
  exit 1
fi

if [ ! -x "$script_dir/personal-media-tracker" ]; then
  printf '%s\n' "The Linux archive is incomplete: personal-media-tracker is missing." >&2
  exit 1
fi

source_version=$("$script_dir/personal-media-tracker" --version)
if [ -f "$version_file" ]; then
  expected_version=$(tr -d '[:space:]' < "$version_file")
  if [ "$source_version" != "$expected_version" ]; then
    printf '%s\n' "The extracted files do not all belong to PMT $expected_version." >&2
    printf '%s\n' "Delete this extracted folder and unpack the latest archive again." >&2
    exit 1
  fi
fi

mkdir -p "$data_home" "$applications_dir"
if [ "$script_dir" != "$install_dir" ]; then
  stage_dir="$data_home/.${app_name}-install-$$"
  previous_dir="$data_home/.${app_name}-previous-$$"
  trap 'rm -rf "$stage_dir" "$previous_dir"' EXIT HUP INT TERM
  mkdir -p "$stage_dir"
  cp -R "$script_dir"/. "$stage_dir"/
  chmod +x "$stage_dir/personal-media-tracker"
  installed_version=$("$stage_dir/personal-media-tracker" --version)
  if [ "$installed_version" != "$source_version" ]; then
    printf '%s\n' "The staged PMT executable failed its version check." >&2
    exit 1
  fi
  if [ -e "$install_dir" ]; then
    mv "$install_dir" "$previous_dir"
  fi
  if ! mv "$stage_dir" "$install_dir"; then
    if [ -e "$previous_dir" ]; then
      mv "$previous_dir" "$install_dir"
    fi
    exit 1
  fi
  rm -rf "$previous_dir"
  trap - EXIT HUP INT TERM
fi
chmod +x "$install_dir/personal-media-tracker"

installed_version=$("$install_dir/personal-media-tracker" --version)
if [ "$installed_version" != "$source_version" ]; then
  printf '%s\n' "The installed PMT version does not match the extracted archive." >&2
  exit 1
fi

sed \
  -e "s|^Exec=.*|Exec=$install_dir/personal-media-tracker|" \
  -e "s|^Icon=.*|Icon=$install_dir/personal-media-tracker.png|" \
  "$install_dir/personal-media-tracker.desktop" > "$desktop_file"
chmod 644 "$desktop_file"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$applications_dir" >/dev/null 2>&1 || true
fi

printf '%s\n' "Personal Media Tracker $installed_version was installed for this user."
printf '%s\n' "Open it from your application launcher or run:"
printf '  %s\n' "$install_dir/personal-media-tracker"
