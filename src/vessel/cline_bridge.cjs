"use strict";

// Additive observation data for the exact Cline 4.1.17 VS Code bridge.
// No inferred IDs, tool approvals, control output, or process execution here.
function factory(createFactory, context, getSessionId) {
  // Capture before asynchronous hook discovery can yield to a UI task switch.
  const rootSessionId = getSessionId?.();
  return {
    async create(...args) {
      const runner = await createFactory().create(...args);
      return {
        get isNoOp() { return runner.isNoOp; },
        run(params) {
          const snapshot = context.snapshot;
          const native = {
            schema: 2,
            rootSessionId,
            conversationId: snapshot.conversationId,
            agentId: snapshot.agentId,
            runId: snapshot.runId,
            iteration: snapshot.iteration,
          };
          if (context.toolCall) {
            native.toolCall = {
              id: context.toolCall.toolCallId,
              name: context.toolCall.toolName,
              input: context.input,
            };
          }
          if (context.toolCall && context.result) {
            native.toolResult = {
              ...native.toolCall,
              output: context.result.output,
              success: !context.result.isError,
              error: context.result.isError === true ? String(context.result.output) : undefined,
            };
          }
          // The original parameters and control response retain their semantics.
          return runner.run({ ...params, vesselCapture: native });
        },
      };
    },
  };
}

class CommandObservation {
  constructor(output, exitCode) {
    this.output = output;
    this.exitCode = Number.isInteger(exitCode) ? exitCode : null;
  }
}

function commandResult(query, output) {
  if (output instanceof CommandObservation) {
    return {
      query,
      result: output.output,
      success: true,
      exitCode: output.exitCode,
      completed: output.exitCode !== null,
    };
  }
  // Detached or unsupported executors return their original result. An outer
  // success flag alone is deliberately insufficient for a successful receipt.
  return { query, result: output, success: true };
}

module.exports = { factory, CommandObservation, commandResult };
