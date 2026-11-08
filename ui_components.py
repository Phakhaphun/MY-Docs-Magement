"""Shared offline UI components used by the independently mounted workspaces."""
from html import escape
from pathlib import Path


def bundle_output_picker(html, *, path_id, button_id, label='Save to', editable=False):
    path_id, button_id, label = map(escape, (path_id, button_id, label))
    readonly = '' if editable else ' readonly'
    picker = f'''<div class="destination-field">
      <label for="{path_id}">{label}</label>
      <div class="destination-picker">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
        <input id="{path_id}" class="destination-path" type="text" aria-label="{label}"{readonly}>
        <button id="{button_id}" class="destination-change" type="button" title="Choose output folder">Change folder</button>
      </div>
    </div>'''
    styles = (Path(__file__).parent / 'ui' / 'destination.css').read_text(encoding='utf-8')
    return html.replace('<!-- OUTPUT_PICKER -->', picker).replace('</head>', f'<style>{styles}</style></head>')
