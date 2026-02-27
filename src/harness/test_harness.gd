## TestHarness — Injected by godot-test-mcp. DO NOT EDIT.
## This file is automatically created at launch and removed on stop.
## WebSocket JSON-RPC server for external test automation.
extends Node

var _tcp_server: TCPServer = TCPServer.new()
var _peers: Array = []
var _port: int = 9877
var _ready_for_commands: bool = false

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
		"eval":
			return _cmd_eval(params)
		"pause":
			get_tree().paused = true
			return {"result": {"paused": true}}
		"resume":
			get_tree().paused = false
			return {"result": {"paused": false}}
		_:
			return {"error": {"code": -32601, "message": "Unknown method: %s" % method}}


## ── Generic Godot commands (work with ANY project) ──

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
		var pname: String = prop["name"]
		if prop["usage"] & PROPERTY_USAGE_SCRIPT_VARIABLE:
			var val = node.get(pname)
			if val is bool or val is int or val is float or val is String:
				props[pname] = val
			elif val is Vector2 or val is Vector2i:
				props[pname] = {"x": val.x, "y": val.y}
			elif val is Vector3 or val is Vector3i:
				props[pname] = {"x": val.x, "y": val.y, "z": val.z}
			elif val is Dictionary:
				props[pname] = _safe_dict(val)
			elif val is Array:
				props[pname] = _safe_array(val)
	return {"result": {"path": str(node.get_path()), "class": node.get_class(), "name": node.name, "properties": props}}


func _cmd_get_property(params: Dictionary) -> Dictionary:
	var path: String = str(params.get("path", ""))
	var property: String = str(params.get("property", ""))
	var node: Node = get_tree().root.get_node_or_null(path)
	if node == null:
		return {"error": {"code": -1, "message": "Node not found: %s" % path}}
	if not property in node:
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


## ── Serialization helpers ──

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
