## TestHarness - Injected by godot-test-mcp. DO NOT EDIT.
## This file is automatically created at launch and removed on stop.
## WebSocket JSON-RPC server for external test automation.
extends Node

var _tcp_server: TCPServer = TCPServer.new()
var _peers: Array = []
var _port: int = 9877
var _ready_for_commands: bool = false

const _BLOCKED_PATTERNS: PackedStringArray = [
	"OS.", "FileAccess.", "DirAccess.", "ClassDB.",
	"Engine.get_singleton", "JavaScriptBridge.",
	"WorkerThreadPool.", "Thread.new",
	"ResourceSaver.", "ResourceLoader.load",
	"ProjectSettings.save",
]

func _ready() -> void:
	# Read port from command line: --test-harness-port=9877
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--test-harness-port="):
			_port = int(arg.split("=")[1])

	var err: int = _tcp_server.listen(_port, "127.0.0.1")
	if err != OK:
		push_error("TestHarness: Failed to listen on port %d" % _port)
		return
	print("TEST_HARNESS_READY:%d" % _port)
	_ready_for_commands = true


func _process(_delta: float) -> void:
	if not _ready_for_commands:
		return

	# Accept new connections
	while _tcp_server.is_connection_available():
		var tcp: StreamPeerTCP = _tcp_server.take_connection()
		var ws := WebSocketPeer.new()
		ws.accept_stream(tcp)
		_peers.append(ws)

	# Poll peers
	var to_remove: Array[int] = []
	for i in range(_peers.size()):
		var ws: WebSocketPeer = _peers[i]
		ws.poll()
		match ws.get_ready_state():
			WebSocketPeer.STATE_OPEN:
				while ws.get_available_packet_count() > 0:
					var text: String = ws.get_packet().get_string_from_utf8()
					var response: String = _handle_message(text)
					ws.send_text(response)
			WebSocketPeer.STATE_CLOSED:
				to_remove.append(i)
	for i in range(to_remove.size() - 1, -1, -1):
		_peers.remove_at(to_remove[i])


func _handle_message(text: String) -> String:
	var json := JSON.new()
	if json.parse(text) != OK:
		return JSON.stringify({"id": null, "error": {"code": -32700, "message": "Parse error"}})
	var req: Dictionary = json.data
	var id = req.get("id")
	var method: String = str(req.get("method", ""))
	var params: Dictionary = req.get("params", {}) if req.get("params") is Dictionary else {}
	var result: Dictionary = _dispatch(method, params)
	if result.has("error"):
		return JSON.stringify({"id": id, "error": result["error"]})
	return JSON.stringify({"id": id, "result": result.get("result", {})})


func _dispatch(method: String, params: Dictionary) -> Dictionary:
	match method:
		"ping":
			return {"result": {"pong": true}}
		"get_tree_info":
			return _cmd_get_tree_info()
		"get_node":
			return _cmd_get_node(params)
		"get_property":
			return _cmd_get_property(params)
		"set_property":
			return _cmd_set_property(params)
		"call_method":
			return _cmd_call_method(params)
		"get_nodes_in_group":
			return _cmd_get_nodes_in_group(params)
		"get_capabilities":
			return _cmd_get_capabilities(params)
		"capture_screenshot":
			return _cmd_capture_screenshot(params)
		"capture_frame":
			return _cmd_capture_frame(params)
		"get_visual_snapshot":
			return _cmd_get_visual_snapshot(params)
		"send_input":
			return _cmd_send_input(params)
		"wait_frames":
			return _cmd_wait_frames(params)
		"eval":
			return _cmd_eval(params)
		"inspect":
			return _cmd_inspect(params)
		"run_script":
			return _cmd_run_script(params)
		"batch":
			return _cmd_batch(params)
		"pause":
			get_tree().paused = true
			return {"result": {"paused": true}}
		"resume":
			get_tree().paused = false
			return {"result": {"paused": false}}
		_:
			return {"error": {"code": -32601, "message": "Unknown method: %s" % method}}


## -- Generic Godot commands (work with ANY project) --

func _cmd_get_tree_info() -> Dictionary:
	var root := get_tree().root
	var info := {
		"root_children": [],
		"node_count": _count_nodes(root),
		"current_scene": "",
		"paused": get_tree().paused,
	}
	for child in root.get_children():
		info["root_children"].append({"name": child.name, "class": child.get_class()})
	if get_tree().current_scene:
		info["current_scene"] = get_tree().current_scene.name
	return {"result": info}


func _cmd_get_node(params: Dictionary) -> Dictionary:
	var path: String = str(params.get("path", ""))
	var node: Node = get_tree().root.get_node_or_null(path)
	if node == null:
		return {"error": {"code": -1, "message": "Node not found: %s" % path}}

	var props: Dictionary = {}
	for prop in node.get_property_list():
		if not _include_property(prop):
			continue
		var pname: String = str(prop.get("name", ""))
		props[pname] = _safe_value(node.get(pname))

	return {
		"result": {
			"path": str(node.get_path()),
			"class": node.get_class(),
			"name": node.name,
			"properties": props,
		}
	}


func _cmd_get_property(params: Dictionary) -> Dictionary:
	var path: String = str(params.get("path", ""))
	var property: String = str(params.get("property", ""))
	var node: Node = get_tree().root.get_node_or_null(path)
	if node == null:
		return {"error": {"code": -1, "message": "Node not found: %s" % path}}
	if not _has_property(node, property):
		return {"error": {"code": -1, "message": "Property '%s' not found on %s" % [property, path]}}
	var val = node.get(property)
	return {"result": {"path": path, "property": property, "value": _safe_value(val)}}


func _cmd_set_property(params: Dictionary) -> Dictionary:
	var path: String = str(params.get("path", ""))
	var property: String = str(params.get("property", ""))
	var value = params.get("value")
	var node: Node = get_tree().root.get_node_or_null(path)
	if node == null:
		return {"error": {"code": -1, "message": "Node not found: %s" % path}}
	node.set(property, value)
	return {"result": {"ok": true}}


func _cmd_call_method(params: Dictionary) -> Dictionary:
	var path: String = str(params.get("path", ""))
	var method_name: String = str(params.get("method", ""))
	var args: Array = params.get("args", [])
	var node: Node = get_tree().root.get_node_or_null(path)
	if node == null:
		return {"error": {"code": -1, "message": "Node not found: %s" % path}}
	if not node.has_method(method_name):
		return {"error": {"code": -1, "message": "Method '%s' not found on %s" % [method_name, path]}}
	var result = node.callv(method_name, args)
	return {"result": {"return_value": _safe_value(result)}}


func _cmd_get_nodes_in_group(params: Dictionary) -> Dictionary:
	var group: String = str(params.get("group", ""))
	var nodes: Array = get_tree().get_nodes_in_group(group)
	var result: Array = []
	for n in nodes:
		result.append({"name": n.name, "path": str(n.get_path()), "class": n.get_class()})
	return {"result": {"group": group, "count": nodes.size(), "nodes": result}}


func _cmd_get_capabilities(_params: Dictionary) -> Dictionary:
	var nodes: Array = []
	var groups_seen: Dictionary = {}
	var hook_methods: Array = []
	var hook_targets: Array = []
	var mutable_properties: Array = []
	_collect_capabilities(
		get_tree().root,
		nodes,
		groups_seen,
		hook_methods,
		hook_targets,
		mutable_properties
	)

	return {
		"result": {
			"nodes": nodes,
			"groups": groups_seen.keys(),
			"groups_count": groups_seen.size(),
			"node_count": nodes.size(),
			"hook_methods": hook_methods,
			"hook_targets": hook_targets,
			"mutable_properties": mutable_properties,
			"visual_channels": ["screenshot", "frame", "snapshot"],
			"input_channels": ["action", "key"],
			"has_test_hooks": hook_methods.size() > 0,
		}
	}


func _cmd_capture_screenshot(params: Dictionary) -> Dictionary:
	var requested_path: String = str(params.get("path", "")).strip_edges()
	var output_path: String = requested_path if requested_path != "" else "user://godot-test-mcp/screenshot_%d.png" % Time.get_unix_time_from_system()

	var viewport := get_viewport()
	if viewport == null:
		return {"error": {"code": -1, "message": "Viewport not available"}}

	var image: Image = viewport.get_texture().get_image()
	if image == null:
		return {"error": {"code": -1, "message": "Failed to capture viewport image"}}

	_ensure_output_dir(output_path)
	var err: int = image.save_png(output_path)
	if err != OK:
		return {"error": {"code": -1, "message": "save_png failed with code %d" % err}}

	return {
		"result": {
			"path": output_path,
			"width": image.get_width(),
			"height": image.get_height(),
		}
	}


func _cmd_capture_frame(params: Dictionary) -> Dictionary:
	var requested_path: String = str(params.get("path", "")).strip_edges()
	var output_path: String = requested_path if requested_path != "" else "user://godot-test-mcp/frame_%d.png" % Time.get_unix_time_from_system()
	var capture_result: Dictionary = _cmd_capture_screenshot({"path": output_path})
	if capture_result.has("error"):
		return capture_result
	return {"result": {"path": output_path}}


func _cmd_get_visual_snapshot(params: Dictionary) -> Dictionary:
	var max_nodes: int = int(params.get("max_nodes", 500))
	if max_nodes <= 0:
		max_nodes = 500

	var nodes: Array = []
	_collect_visual_nodes(get_tree().root, nodes, max_nodes)

	var visible_count: int = 0
	for node_info in nodes:
		if bool(node_info.get("visible", false)):
			visible_count += 1

	var visible_rect: Rect2 = get_viewport().get_visible_rect()
	return {
		"result": {
			"nodes": nodes,
			"visible_node_count": visible_count,
			"total_node_count": nodes.size(),
			"viewport": {
				"width": visible_rect.size.x,
				"height": visible_rect.size.y,
			},
		}
	}


func _cmd_send_input(params: Dictionary) -> Dictionary:
	var action: String = str(params.get("action", "")).strip_edges()
	var key_name: String = str(params.get("key", "")).strip_edges()
	var pressed: bool = bool(params.get("pressed", true))

	if action != "":
		var action_event := InputEventAction.new()
		action_event.action = action
		action_event.pressed = pressed
		action_event.strength = float(params.get("strength", 1.0))
		Input.parse_input_event(action_event)
		return {"result": {"ok": true, "kind": "action", "action": action, "pressed": pressed}}

	if key_name != "":
		var keycode: int = OS.find_keycode_from_string(key_name)
		if keycode == 0:
			return {"error": {"code": -1, "message": "Unknown key name: %s" % key_name}}
		var key_event := InputEventKey.new()
		key_event.keycode = keycode
		key_event.pressed = pressed
		Input.parse_input_event(key_event)
		return {"result": {"ok": true, "kind": "key", "key": key_name, "pressed": pressed}}

	return {"error": {"code": -1, "message": "send_input requires 'action' or 'key'"}}


func _cmd_wait_frames(params: Dictionary) -> Dictionary:
	var frames: int = int(params.get("frames", 1))
	if frames < 1:
		frames = 1
	# NOTE: OS.delay_msec() blocks the Godot main thread.
	# The game loop does NOT advance during this wait.
	# This is a time-based approximation, not true frame advancement.
	# For accurate frame stepping, use the Godot editor's built-in pause/step.
	var physics_fps: float = float(ProjectSettings.get_setting("physics/common/physics_ticks_per_second", 60))
	var fallback_fps: float = 60.0
	var effective_fps: float = physics_fps if physics_fps > 0.0 else fallback_fps
	var wait_ms: int = int(ceil((1000.0 / effective_fps) * frames))
	OS.delay_msec(wait_ms)
	return {"result": {"waited_frames": frames, "waited_ms": wait_ms, "fps_used": effective_fps}}


func _cmd_eval(params: Dictionary) -> Dictionary:
	var expr_str: String = str(params.get("expression", ""))
	var expr := Expression.new()
	var err: int = expr.parse(expr_str)
	if err != OK:
		return {"error": {"code": -1, "message": "Parse error: %s" % expr.get_error_text()}}
	var result = expr.execute([], get_tree().root)
	if expr.has_execute_failed():
		return {"error": {"code": -1, "message": "Execution error: %s" % expr.get_error_text()}}
	return {"result": {"value": _safe_value(result)}}


func _cmd_inspect(params: Dictionary) -> Dictionary:
	var expr_str: String = str(params.get("expression", ""))
	var depth: int = int(params.get("depth", 0))
	if depth > 3:
		depth = 3

	var expr := Expression.new()
	var err: int = expr.parse(expr_str)
	if err != OK:
		return {"error": {"code": -1, "message": "Parse error: %s" % expr.get_error_text()}}
	var obj = expr.execute([], get_tree().root)
	if expr.has_execute_failed():
		return {"error": {"code": -1, "message": "Execution error: %s" % expr.get_error_text()}}
	if obj == null:
		return {"error": {"code": -1, "message": "Expression returned null"}}

	var result: Dictionary = _inspect_object(obj, depth)
	return {"result": result}


func _inspect_object(obj: Variant, depth: int) -> Dictionary:
	var result: Dictionary = {}
	result["type"] = type_string(typeof(obj))

	if not (obj is Object):
		result["value"] = _safe_value(obj)
		return result

	result["class"] = obj.get_class()

	var script = obj.get_script()
	if script:
		result["script"] = script.resource_path

	# Properties - language-agnostic (stored + script vars)
	var properties: Dictionary = {}
	for prop in obj.get_property_list():
		if not _include_property(prop):
			continue
		var pname: String = str(prop.get("name", ""))
		var val = obj.get(pname)
		properties[pname] = {
			"type": type_string(int(prop.get("type", TYPE_NIL))),
			"value": _safe_value(val),
		}
	result["properties"] = properties

	# Methods - generic object methods, filtered for readability
	var methods: Array = []
	for method in obj.get_method_list():
		var mname: String = str(method.get("name", ""))
		if mname == "":
			continue
		if mname.begins_with("_") and mname != "_ready" and mname != "_process":
			continue
		var args: Array = []
		var raw_args = method.get("args", [])
		if raw_args is Array:
			for arg in raw_args:
				if arg is Dictionary:
					args.append({
						"name": str(arg.get("name", "")),
						"type": type_string(int(arg.get("type", TYPE_NIL))),
					})
		methods.append({
			"name": mname,
			"args": args,
			"return_type": type_string(TYPE_NIL),
		})
		if methods.size() >= 300:
			break
	result["methods"] = methods

	# Signals - generic object signals
	var signals: Array = []
	for sig in obj.get_signal_list():
		var sig_name: String = str(sig.get("name", ""))
		if sig_name == "":
			continue
		var sig_args: Array = []
		var raw_sig_args = sig.get("args", [])
		if raw_sig_args is Array:
			for arg in raw_sig_args:
				if arg is Dictionary:
					sig_args.append({
						"name": str(arg.get("name", "")),
						"type": type_string(int(arg.get("type", TYPE_NIL))),
					})
		signals.append({"name": sig_name, "args": sig_args})
		if signals.size() >= 200:
			break
	result["signals"] = signals

	# Groups and children (only for Node)
	if obj is Node:
		result["groups"] = []
		for g in obj.get_groups():
			var gname: String = str(g)
			if not gname.begins_with("_"):
				result["groups"].append(gname)

		if depth > 0:
			var children: Array = []
			for child in obj.get_children():
				children.append(_inspect_object(child, depth - 1))
			result["children"] = children
		else:
			var child_names: Array = []
			for child in obj.get_children():
				child_names.append({"name": child.name, "class": child.get_class()})
			result["children"] = child_names

	return result


func _cmd_run_script(params: Dictionary) -> Dictionary:
	var code: String = str(params.get("code", ""))

	# Security check - block dangerous patterns
	for pattern in _BLOCKED_PATTERNS:
		if code.find(pattern) != -1:
			return {"error": {"code": -2, "message": "Blocked: '%s' access is not allowed in run_script" % pattern}}

	# Build dynamic GDScript
	var script := GDScript.new()
	var source: String = "extends RefCounted\n\n"
	source += "var _tree_ref: SceneTree\n\n"
	source += "func get_tree() -> SceneTree:\n\treturn _tree_ref\n\n"
	source += "func execute() -> Variant:\n"

	var lines: PackedStringArray = code.split("\n")
	for line in lines:
		source += "\t" + line + "\n"

	# If user code doesn't have explicit return, add return null
	var has_return: bool = false
	for line in lines:
		if line.strip_edges().begins_with("return ") or line.strip_edges() == "return":
			has_return = true
			break
	if not has_return:
		source += "\treturn null\n"

	script.source_code = source

	# Compile
	var err: int = script.reload()
	if err != OK:
		return {"error": {"code": -1, "message": "Compile error (code %d). Source:\n%s" % [err, source]}}

	# Execute
	var instance: RefCounted = script.new()
	instance._tree_ref = get_tree()
	var result = instance.execute()

	return {"result": {"value": _safe_value(result)}}


func _cmd_batch(params: Dictionary) -> Dictionary:
	var expressions: Array = params.get("expressions", [])
	var results: Array = []

	for expr_str in expressions:
		var expr := Expression.new()
		var err: int = expr.parse(str(expr_str))
		if err != OK:
			results.append({"expr": str(expr_str), "status": "error", "message": "Parse error: %s" % expr.get_error_text()})
			continue
		var val = expr.execute([], get_tree().root)
		if expr.has_execute_failed():
			results.append({"expr": str(expr_str), "status": "error", "message": "Execution error: %s" % expr.get_error_text()})
			continue
		results.append({"expr": str(expr_str), "status": "ok", "value": _safe_value(val)})

	return {"result": results}


## -- Helpers --

func _include_property(prop: Dictionary) -> bool:
	var usage: int = int(prop.get("usage", 0))
	var has_storage: bool = (usage & PROPERTY_USAGE_STORAGE) != 0
	var has_script_var: bool = (usage & PROPERTY_USAGE_SCRIPT_VARIABLE) != 0
	if not has_storage and not has_script_var:
		return false
	var pname: String = str(prop.get("name", ""))
	if pname == "" or pname.begins_with("_"):
		return false
	return true


func _has_property(obj: Object, property_name: String) -> bool:
	for prop in obj.get_property_list():
		if str(prop.get("name", "")) == property_name:
			return true
	return false


func _collect_capabilities(
	node: Node,
	nodes: Array,
	groups_seen: Dictionary,
	hook_methods: Array,
	hook_targets: Array,
	mutable_properties: Array
) -> void:
	if nodes.size() >= 500:
		return
	nodes.append({"name": node.name, "path": str(node.get_path()), "class": node.get_class()})

	for g in node.get_groups():
		var gname: String = str(g)
		if not gname.begins_with("_"):
			groups_seen[gname] = true

	for method in node.get_method_list():
		var mname: String = str(method.get("name", ""))
		if mname.begins_with("test_mcp_") and not hook_methods.has(mname):
			hook_methods.append(mname)
		if mname.begins_with("test_mcp_"):
			var target := {"path": str(node.get_path()), "method": mname}
			var target_key: String = "%s::%s" % [target["path"], target["method"]]
			var exists: bool = false
			for existing in hook_targets:
				if existing is Dictionary:
					var existing_key: String = "%s::%s" % [str(existing.get("path", "")), str(existing.get("method", ""))]
					if existing_key == target_key:
						exists = true
						break
			if not exists:
				hook_targets.append(target)

	for prop in node.get_property_list():
		if not _include_property(prop):
			continue
		var pname: String = str(prop.get("name", ""))
		var prop_key: String = "%s.%s" % [str(node.get_path()), pname]
		if not mutable_properties.has(prop_key):
			mutable_properties.append(prop_key)
		if mutable_properties.size() >= 300:
			break

	for child in node.get_children():
		if nodes.size() >= 500:
			break
		if child is Node:
			_collect_capabilities(
				child,
				nodes,
				groups_seen,
				hook_methods,
				hook_targets,
				mutable_properties
			)


func _collect_visual_nodes(node: Node, out: Array, max_nodes: int) -> void:
	if out.size() >= max_nodes:
		return

	if node is CanvasItem:
		var canvas_item: CanvasItem = node
		var entry: Dictionary = {
			"name": node.name,
			"path": str(node.get_path()),
			"class": node.get_class(),
			"visible": canvas_item.visible,
		}

		if node is Control:
			var control: Control = node
			var rect: Rect2 = control.get_global_rect()
			entry["rect"] = {
				"x": rect.position.x,
				"y": rect.position.y,
				"w": rect.size.x,
				"h": rect.size.y,
			}
			if _has_property(control, "text"):
				entry["text"] = str(control.get("text"))
		elif node is Node2D:
			var node2d: Node2D = node
			entry["position"] = {"x": node2d.global_position.x, "y": node2d.global_position.y}

		out.append(entry)

	for child in node.get_children():
		if child is Node:
			_collect_visual_nodes(child, out, max_nodes)
		if out.size() >= max_nodes:
			return


func _ensure_output_dir(path_hint: String) -> void:
	var global_path: String = ProjectSettings.globalize_path(path_hint)
	var base_dir: String = global_path.get_base_dir()
	if base_dir != "":
		DirAccess.make_dir_recursive_absolute(base_dir)


func _safe_value(val) -> Variant:
	if val == null:
		return null
	if val is bool or val is int or val is float or val is String:
		return val
	if val is Vector2 or val is Vector2i:
		return {"x": val.x, "y": val.y}
	if val is Vector3 or val is Vector3i:
		return {"x": val.x, "y": val.y, "z": val.z}
	if val is Dictionary:
		return _safe_dict(val)
	if val is Array:
		return _safe_array(val)
	return str(val)


func _safe_dict(d: Dictionary, depth: int = 0) -> Dictionary:
	if depth > 3:
		return {"_truncated": true}
	var result: Dictionary = {}
	for key in d:
		result[str(key)] = _safe_value(d[key]) if depth < 3 else str(d[key])
	return result


func _safe_array(a: Array, depth: int = 0) -> Array:
	if depth > 3 or a.size() > 100:
		return [{"_truncated": true, "size": a.size()}]
	var result: Array = []
	for item in a:
		result.append(_safe_value(item))
	return result


func _count_nodes(node: Node) -> int:
	var count: int = 1
	for child in node.get_children():
		count += _count_nodes(child)
	return count


func _exit_tree() -> void:
	for ws in _peers:
		ws.close()
	_peers.clear()
	_tcp_server.stop()
