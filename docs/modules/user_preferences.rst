user_preferences — 用户收藏夹和读取偏移量
===============================================

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

   # 获取收藏目录
   user_preferences.get_user_starred("ou_abc123")
   # → ["/home/user/projects/ai", "/home/user/dotfiles"]

   # 切换收藏状态
   user_preferences.toggle_user_star("ou_abc123", "/home/user/project")
   # → True（已收藏）/ False（已取消收藏）

   # 更新 MRU（最近使用）— 在窗口创建后调用
   user_preferences.update_user_mru("ou_abc123", "/home/user/new-project")
   # → 添加到 MRU 开头，去重，最多保留 5 条

**读取偏移量**

.. code-block:: python

   user_preferences.get_user_window_offset("ou_abc123", "window_1")
   # → 4821 （上一次看到的字节偏移）

   user_preferences.update_user_window_offset("ou_abc123", "window_1", 5100)

注意：读取偏移量目前在处理器中尚未接入——它们存在
是为了将来实现每个用户"从上次阅读位置继续"功能。

序列化
-------------

``to_dict()`` 生成一个可用于网关状态文件 JSON 序列化的普通字典。键为用户 ID（str）。

``from_dict(d)`` 从持久化数据恢复，不调用 ``_schedule_save``
（与 ccgram 原始实现不同——从磁盘加载不应触发写入）。

调用栈
-----------

会话创建 — 保存 MRU
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   session_creation._create_window(ctx, path, provider, mode)
   → user_preferences.update_user_mru(ctx.user_id, path)
       → resolved = str(Path(path).resolve())
       → mru = favs.get("mru", [])  ["a", "b"]
       → mru = [resolved] + [p for p in mru if p != resolved]
       → favs["mru"] = mru[:5]

切换目录星标
~~~~~~~~~~~~~~~~~~~~~~~~

::

   session_creation.handle_dir_callback(ctx)
   → ctx.value.startswith("db:star:")?
   → dir_path = _dec(ctx.value[len("db:star:"):])
   → user_preferences.toggle_user_star(ctx.user_id, dir_path)
       → resolved = str(Path(dir_path).resolve())
       → starred = favs.get("starred", [])
       → resolved in starred? → 移除 → 返回 False
       → 否则：追加 → 返回 True
       → favs["starred"] = starred
