import { readFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type ToolSchema = { name: string; description: string; inputSchema: any };
type BridgeConfig = { bridge_url: string; token: string; tools: ToolSchema[] };

export default function (pi: ExtensionAPI) {
	const configPath = process.env.TCB_REMOTE_MCP_CONFIG;
	if (!configPath) return;
	const load = (): BridgeConfig => JSON.parse(readFileSync(configPath, "utf8"));
	const config = load();
	async function call(tool: string, args: Record<string, unknown>, signal?: AbortSignal) {
		const current = load();
		const url = new URL(current.bridge_url);
		if (!["http:", "https:"].includes(url.protocol) || !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
			|| url.username || url.password || url.search || url.hash) throw new Error("Invalid remote bridge URL");
		const timeout = AbortSignal.timeout((Number(args.timeout_seconds || 60) + 15) * 1000);
		const response = await fetch(`${current.bridge_url.replace(/\/+$/, "")}/api/remote/agent-tools`, {
			method: "POST", redirect: "error",
			headers: { "Content-Type": "application/json", "X-TCB-Remote-Token": current.token },
			body: JSON.stringify({ tool, arguments: args }),
			signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
		});
		const reader = response.body?.getReader();
		if (!reader) throw new Error("Empty remote bridge response");
		const chunks: Uint8Array[] = [];
		let size = 0;
		try {
			while (true) {
				const { value, done } = await reader.read();
				if (done) break;
				size += value.length;
				if (size > 512000) throw new Error("Remote response exceeded output limit");
				chunks.push(value);
			}
		} finally {
			await reader.cancel();
		}
        const result = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        if (!response.ok || result?.ok !== true) {
            const error = result?.error;
            const message = error && typeof error.message === "string"
                ? `${error.code || "remote_error"}: ${error.message}` : `Remote bridge HTTP ${response.status}`;
            throw new Error(`${message.slice(0, 1800)}; operation was not retried`);
        }
		return { content: [{ type: "text" as const, text: JSON.stringify(result.data) }], details: {} };
	}
	function register(name: string, definition: ToolSchema, map = (params: any) => params) {
		pi.registerTool({
			name, label: name, description: definition.description,
			promptSnippet: definition.description,
			promptGuidelines: ["All paths and commands target the remote SSH workspace. Read remote repository instructions before edits."],
			parameters: definition.inputSchema,
			async execute(_id, params, signal) { return call(definition.name, map(params), signal); },
		});
	}
	const byName = Object.fromEntries(config.tools.map((tool) => [tool.name, tool]));
	for (const tool of config.tools) register(`remote_${tool.name}`, tool);
	for (const name of ["read", "write"]) register(name, byName[name]);
	register("ls", byName.list);
	register("edit", {
		...byName.edit,
		inputSchema: {
			type: "object", additionalProperties: false, required: ["path", "oldText", "newText"],
			properties: {
				path: byName.edit.inputSchema.properties.path,
				oldText: byName.edit.inputSchema.properties.old_text,
				newText: byName.edit.inputSchema.properties.new_text,
			},
		},
	}, (params) => ({ path: params.path, old_text: params.oldText, new_text: params.newText }));
	register("bash", {
		...byName.exec,
		inputSchema: {
			type: "object", additionalProperties: false, required: ["command"],
			properties: {
				command: byName.exec.inputSchema.properties.commands.items,
				timeout: byName.exec.inputSchema.properties.timeout_seconds,
			},
		},
	}, (params) => ({ commands: [params.command], ...(params.timeout ? { timeout_seconds: params.timeout } : {}) }));
}
