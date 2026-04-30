user_preferences — 用户 MRU 目录和读取偏移量
================================================

源码：src/cclark/user_preferences.py

存储每个飞书用户收藏的目录和转录本读取偏移量。
改编自 ``ccgram/user_preferences.py``，将用户 ID 改为 str（而非 int）。

``UserPreferences``
-------------------

.. code-block:: python

   from cclark.user_preferences import user_preferences

   user_preferences.to_dict()    # 序列化用于状态持久化
   user_preferences.from_dict(d) # 从状态文件恢复

数据模型
----------

.. code-block:: python

   user_dir_favorites: dict[str, dict[str, list[str]]]
   # user_id → {"starred": [...], "mru": [...]}

   user_window_offsets: dict[str, dict[str, int]]
   # user_id → {window_id → byte_offset}

方法
-------

**目录收藏**

.. code-block:: python

   # 获取星标目录
   user_preferences.get_user_starred("ou_abc123")
   # → ["/home/user/projects/ai", "/home/user/dotfiles"]

   # 切换收藏状态
   user_preferences.toggle_user_star("ou_abc123", "/home/user/project")
   # → True（已收藏）/ False（已取消收藏）

   # 获取最近使用目录
   user_preferences.get_user_mru("ou_abc123")
   # → ["/home/user/projects/api", "/home/user/projects/web"]

   # 更新 MRU（最近使用）— 在窗口创建后调用
   user_preferences.update_user_mru("ou_abc123", "/home/user/new-project")
   # → 添加到 MRU 开头，去重，最多保留 5 条

**读取偏移量**

.. code-block:: python

   user_preferences.get_user_window_offset("ou_abc123", "@0")
   # → 4821 （上一次看到的字节偏移）

   user_preferences.update_user_window_offset("ou_abc123", "@0", 5100)

注意：读取偏移量目前在处理器中尚未接入——它们存在
是为了将来实现每个用户"从上次阅读位置继续"功能。

持久化
------------

``to_dict()`` 生成一个可用于网关状态文件 JSON 序列化的普通字典。
键为用户 ID（str）。

``from_dict(d)`` 从持久化数据恢复，不调用 ``_schedule_save``
（从磁盘加载不应触发写入）。

持久化由 ``unified_icc.window_state_store`` 通过
``WindowStateStore`` 的序列化 pipeline 调用。

调用栈
-----------

会话创建 — 保存 MRU
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   session_creation._handle_browse()
   → user_preferences.update_user_mru(event.user_id, current_path)
       → resolved = str(Path(current_path).resolve())
       → mru = favs.get("mru", [])
       → mru = [resolved] + [p for p in mru if p != resolved]
       → favs["mru"] = mru[:5]
       → window_store._schedule_save()  [包含在 window_state_store.json 中]
