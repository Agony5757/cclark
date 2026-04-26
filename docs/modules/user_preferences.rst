user_preferences — Per-User Favourites and Read Offsets
=========================================================

Source: src/cclark/user_preferences.py

Stores per-Feishu-user starred directories and transcript read offsets.
Adapted from ``ccgram/user_preferences.py`` with str (not int) user IDs.

``UserPreferences``
-------------------

.. code-block:: python

   from cclark.user_preferences import user_preferences

   user_preferences.to_dict()    # serialize for state persistence
   user_preferences.from_dict(d) # restore from state file

Data model
----------

.. code-block:: python

   user_dir_favorites: dict[str, dict[str, list[str]]]
   # user_id → {"starred": [...], "mru": [...]}

   user_window_offsets: dict[str, dict[str, int]]
   # user_id → {window_id → byte_offset}

Methods
-------

**Directory favorites**

.. code-block:: python

   # Get starred directories
   user_preferences.get_user_starred("ou_abc123")
   # → ["/home/user/projects/ai", "/home/user/dotfiles"]

   # Toggle star on/off
   user_preferences.toggle_user_star("ou_abc123", "/home/user/project")
   # → True (now starred) / False (now unstarred)

   # Update MRU (most-recently-used) — called after window creation
   user_preferences.update_user_mru("ou_abc123", "/home/user/new-project")
   # → prepends to MRU, dedupes, caps at 5 entries

**Read offsets**

.. code-block:: python

   user_preferences.get_user_window_offset("ou_abc123", "window_1")
   # → 4821  (last seen byte offset)

   user_preferences.update_user_window_offset("ou_abc123", "window_1", 5100)

Note: read offsets are not currently wired up in the handlers — they are
present for future use when implementing per-user "catch up from last read"
functionality.

Serialization
-------------

``to_dict()`` produces a plain dict suitable for JSON serialization in the
gateway's state file. Keys are user IDs (str).

``from_dict(d)`` restores from persisted data without calling ``_schedule_save``
(the way ccgram's original does — loading from disk must not trigger a write).

Call stacks
-----------

Session creation — save MRU
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   session_creation._create_window(ctx, path, provider, mode)
   → user_preferences.update_user_mru(ctx.user_id, path)
       → resolved = str(Path(path).resolve())
       → mru = favs.get("mru", [])  ["a", "b"]
       → mru = [resolved] + [p for p in mru if p != resolved]
       → favs["mru"] = mru[:5]

Toggle star on directory
~~~~~~~~~~~~~~~~~~~~~~~~

::

   session_creation.handle_dir_callback(ctx)
   → ctx.value.startswith("db:star:")?
   → dir_path = _dec(ctx.value[len("db:star:"):])
   → user_preferences.toggle_user_star(ctx.user_id, dir_path)
       → resolved = str(Path(dir_path).resolve())
       → starred = favs.get("starred", [])
       → resolved in starred? → remove → return False
       → else: append → return True
       → favs["starred"] = starred
