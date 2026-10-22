# Sourced by deploy/sync.sh and deploy/pull.sh (not run on its own).
#
# data/ can be edited in two places: the PC repo and the VM editor (edit.<host>, deploy/interior-editor.service).
# To keep one from silently overwriting the other, every sync/pull leaves a fingerprint of the VM's editable
# files in /opt/interior/.data_stamp; sync.sh compares it before uploading and asks when the VM has newer edits.
DIR=/opt/interior
# what the VM editor may change (and what pull.sh brings back): data/ + the dock layout the editor also writes to gen/
EDITABLE="data client/public/gen/dock.json"
STAMP_CMD="cd $DIR && find $EDITABLE -type f -print0 2>/dev/null | LC_ALL=C sort -z | xargs -0 sha1sum | sha1sum | cut -c1-40"

vm_stamp() {  # remember: the VM's editable files are now what the PC has
  ssh "$1" "$STAMP_CMD > $DIR/.data_stamp"
}

vm_data_unchanged() {  # 0 = VM files match the stamp (or no stamp yet), 1 = edited on the VM since the last sync/pull
  local out cur old
  out=$(ssh "$1" "$STAMP_CMD; cat $DIR/.data_stamp 2>/dev/null || true")
  cur=${out%%$'\n'*}
  old=${out#*$'\n'}
  [[ -z $old || $old == "$out" || $old == "$cur" ]]
}
