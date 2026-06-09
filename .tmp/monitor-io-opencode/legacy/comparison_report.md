# I/O comparison report

- run_id: `legacy-20260609-0829`
- record_dir: `.tmp\monitor-io-opencode\legacy`
- sessions_compared: 7
- issue_count: 6

## Issues

- **warning / completed_without_captured_idle**: Web completed，但记录中未见同 session 的 opencode idle
  - session: `ses_15635e8a0ffeYVpCavqPl0bvso`
  - web_message_id: `msg_794a4e6c1e3145da94e977c39a948b19`

- **warning / completed_without_captured_idle**: Web completed，但记录中未见同 session 的 opencode idle
  - session: `ses_1564e343dffe8eYtr08VgHO0kx`
  - web_message_id: `msg_3e0fca3002d14d8b8a9aaed5a0718e71`

- **warning / completed_without_captured_idle**: Web completed，但记录中未见同 session 的 opencode idle
  - session: `ses_1564ea8ddffe9zdm7d96RSZ3LM`
  - web_message_id: `msg_3982d1c57ff2442fb1ea7fa60bf53651`

- **warning / completed_without_captured_idle**: Web completed，但记录中未见同 session 的 opencode idle
  - session: `ses_1564f0157ffe8XyBmwW86OxT1B`
  - web_message_id: `msg_f32dfca9b1174103b57ff2d125b0d8c3`

- **error / abort_completed**: opencode 见到 abort，但 Web history 标 completed
  - session: `ses_1564fad37ffe6LOrF3mpPzWw8o`
  - web_message_id: `msg_b5d2795bbfa444818e2b501b94f27ff3`

- **warning / completed_without_captured_idle**: Web completed，但记录中未见同 session 的 opencode idle
  - session: `ses_1564fad37ffe6LOrF3mpPzWw8o`
  - web_message_id: `msg_b5d2795bbfa444818e2b501b94f27ff3`

## Checks
- session `ses_15635e8a0ffeYVpCavqPl0bvso`: web_state=completed, web_trace=3, opencode_tools=4, abort=False, idle=False, web_eq_opencode=True, stream_eq_history=True
- session `ses_156363a15ffegcZr0TGUXbbvcT`: web_state=completed, web_trace=0, opencode_tools=0, abort=False, idle=True, web_eq_opencode=True, stream_eq_history=True
- session `ses_15636b6a0ffecTTtw3nWmjXY63`: web_state=completed, web_trace=0, opencode_tools=0, abort=False, idle=True, web_eq_opencode=True, stream_eq_history=True
- session `ses_1564e343dffe8eYtr08VgHO0kx`: web_state=completed, web_trace=3, opencode_tools=1, abort=False, idle=False, web_eq_opencode=True, stream_eq_history=True
- session `ses_1564ea8ddffe9zdm7d96RSZ3LM`: web_state=completed, web_trace=5, opencode_tools=2, abort=False, idle=False, web_eq_opencode=True, stream_eq_history=True
- session `ses_1564f0157ffe8XyBmwW86OxT1B`: web_state=completed, web_trace=0, opencode_tools=0, abort=False, idle=False, web_eq_opencode=True, stream_eq_history=True
- session `ses_1564fad37ffe6LOrF3mpPzWw8o`: web_state=completed, web_trace=1, opencode_tools=0, abort=True, idle=False, web_eq_opencode=True, stream_eq_history=True
