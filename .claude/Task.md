1.Make a comprehensive refactor for the code, you can spwan many subagents or use agent teams to do refactor.

1. use async/await instead of multithreading, remove all multithreading code such as concurrency folder.
2. add global logger. this logger will flush log into workspace/logs folder with yyyy-mm-dd.log. then add logger in code to log enssential info/error
3. remove agent routing and binding. when start Ker, read workspace/agents folder, one folder means one agent. folder name is the agent name.
for example: workspace/agents/ker this is the defualt agent. workspace/agents/luna this is created by user.
under each agent folder contains 
Agent prompt file(Agent.md, Identity.md, Soul.md, Tools.md); 
session folder with session_full_id.txt of session log, such as workspace/agents/ker/session/channel_user_session_name.jsonl (user, assistant, tool_use and tool_result) format. or channel_user_session_name_codex.jsonl/channel_user_session_name_claude_code.jsonl when Ker trigger codex or claude code, also write the codex/claude code log into sessions;
chatHistory folder with a long jsonl format chat history, workspace/agents/ker/chatHistory/chatHistory.jsonl (only have user and assistant no tool_use and tool_result)
skills folder with skills
4.session management. session id is channel_user_session_name.
5.channel refactor, add thinking method for channel to show the thinking status, which is will update with each round agent loop truncated output. kerweb has a api /api/agent/thinking to publish the msg to web. treat cli and kerweb as the same level, for update_job, append_tool_log, publish_telemetry move it to gateway.
all inbound msg from channel, identify inbound msg is a command(start with /) or message, if command run command, if message go to Ker agent main loop.
the inbound msg should have channel, user, session_name, timestamp, media(picture, video, files...), metadata, and other fields.
6.add new folder: llm, handle llm provider, such as AzureOpenAI key, github_copilot oauth.
7.add gateway folder. gateway is the main entry. init all config, handle all inbound/outbound msg from each channel, start cron and heartbeat worker.
update_job, append_tool_log, publish_telemetry, list_agents ...
8. make agent folder only focus on agent work, agent_loop.py, subagent.py, context folder. context folder will construct system prompt from workspace/agents/current_agent_name folder of xx.md, and add agent_name, current_time, current_session_name into prompt.
if not found use itself templates. memeory store, use workspace/MEMORY.md as long term memeory, and use memory_search to get shortern memeory. memory_search search workspace/agents/{current agent name}/chatHistory/chatHistory.jsonl to get shortern memory.
9. delivery use a read/write inbound and outbound queue.
10. refactor capture folder, because claude code and codex will write log into workspace/agents/{current agent name}/session/channel_user_session_name_claude_code.jsonl, no need search them from other place.
don't need anonymizer and secrets.py
11. refactor tools folder more clear, have tool_base, each tool_name.py tool_registry.py, to make it well organzied and well designed. tool should think of on different platform, window, linux, macos.
12. support several commands:
ker cli: start ker cli channel to chat with ker; 
ker gateway: start a gateway to listen all channels except cli(ker_web, other channel with add later);
ker github_copilot login: to login oauth for ker llm provider 
13.the workspace folder like this:
workspace/agents/ker/chatHistory/chatHistory.jsonl
workspace/agents/ker/session/channel_user_session_name.jsonl 
workspace/agents/ker/session/channel_user_session_name_codex.jsonl
workspace/agents/ker/session/channel_user_session_name_claude_code.jsonl
workspace/agents/ker/AGENT.md
workspace/agents/ker/IDENTITY.md
workspace/agents/ker/SOUL.md
workspace/agents/ker/TOOLS.md
workspace/agents/ker/skills/xxxskill/...
workspace/config.json
workspace/MEMORY.md
workspace/logs/2026-03-02.log
workspace/cron/jobs.json
workspace/cron/job_log.json
14.all time logged into workspace must be current machine local time yyyy-mm-dd HH:MM:SS format.
15.write down good docs

workspace/agents/ker/LongTask/task_name_goal.md
workspace/agents/ker/LongTask/task_name_status.md