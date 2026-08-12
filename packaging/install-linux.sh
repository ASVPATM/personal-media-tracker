#!/bin/sh
set -eu

app_name="personal-media-tracker"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
install_dir="$data_home/$app_name"
applications_dir="$data_home/applications"
desktop_file="$applications_dir/$app_name.desktop"

mkdir -p "$install_dir" "$applications_dir"
if [ "$script_dir" != "$install_dir" ]; then
  cp -R "$script_dir"/. "$install_dir"/
fi
chmod +x "$install_dir/personal-media-tracker"

sed \
  -e "s|^Exec=.*|Exec=$install_dir/personal-media-tracker|" \
  -e "s|^Icon=.*|Icon=$install_dir/personal-media-tracker.png|" \
  "$install_dir/personal-media-tracker.desktop" > "$desktop_file"
chmod 644 "$desktop_file"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$applications_dir" >/dev/null 2>&1 || true
fi

printf '%s\n' "Personal Media Tracker was installed for this user."
printf '%s\n' "Open it from your application launcher or run:"
printf '  %s\n' "$install_dir/personal-media-tracker"
