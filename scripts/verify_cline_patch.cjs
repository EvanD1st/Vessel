"use strict";

// Exercise the actual patched functions without loading VS Code, starting a
// model, or writing events into an enrolled VESSEL project.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const source = fs.readFileSync(process.argv[2], "utf8");
const helper = require(require("node:path").resolve(process.argv[3]));
// Inspect the native runtime contract as well as the bridge below: every
// execute() assigns a new run ID before hooks, and snapshot() exposes it.
assert(source.includes('this.state.runId=YZ("run"),this.state.status="running",this.state.iteration=0'));
assert(source.includes('runId:this.state.runId,status:this.state.status,iteration:this.state.iteration'));
function between(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first + start.length);
  assert(first >= 0 && last > first, `Missing native contract ${start}`);
  return source.slice(first, last);
}

const originalKeys = ["taskId", "hookName", "workspaceRoots", "timestamp", "clineVersion",
  "preToolUse", "postToolUse", "taskStart", "taskComplete", "taskCancel", "userPromptSubmit"];
const proto = value => Object.fromEntries(Object.entries(value).filter(([key]) => originalKeys.includes(key)));
const context = vm.createContext({
  __vesselCaptureBridge: helper, Iut: {create:proto,toJSON:proto},
  rQ:"4.1.17", Sm:()=>"fixture-user", Met:async()=>["fixture-project"],
  byr:value=>value, Oe:{error:console.error}, Date, Promise, Symbol, console,
  setTimeout, clearTimeout,
});
vm.runInContext("var Ppt=Symbol(),Mpt;" + between("Mpt=class", ",Tfi=class") + ";", context);
const serializer = between("let o=Iut.toJSON(r);", "o.userPromptSubmit&&");
vm.runInContext(`
  var observations=[];
  class Sink extends Mpt {
    async [Ppt](r) { ${serializer};observations.push(o);return {cancel:false}; }
  }
  var gFe=class { async create(name) { return new Sink(name,['fixture-project']); } };
`, context);
for (const [start, end] of [
  ["function TMu(", "function xyr("], ["function xyr(", "function Qft("],
  ["function Qft(", "function Z$h("], ["function Z$h(", "function kMu("],
  ["function kMu(", "function KS("], ["function KS(", "function Eyr("],
  ["function Eyr(", "var rAi="],
]) vm.runInContext(between(start, end), context);

(async () => {
  context.activeSession="native-root-1";
  context.snapshot={conversationId:"native-turn-1",agentId:"lead",runId:"native-execution-1",iteration:1,
    messages:[{role:"user",content:[{type:"text",text:"READY"}]}]};
  vm.runInContext("var hooks=Eyr({getGlobalSettingsKey:()=>true},()=>{},'fixture-project',()=>activeSession);",context);
  await vm.runInContext("hooks.beforeRun({snapshot})", context);
  // Switching a visible task must not relabel events from an in-flight source.
  context.activeSession="unrelated-root";
  context.call={snapshot:context.snapshot,toolCall:{toolCallId:"call_0",toolName:"run_commands"},
    input:{commands:["probe"]}};
  await vm.runInContext("hooks.beforeTool(call)", context);
  context.result={...context.call,result:{output:[helper.commandResult("probe",new helper.CommandObservation("READY",0))],isError:false}};
  await vm.runInContext("hooks.afterTool(result)", context);
  await vm.runInContext("hooks.afterRun({snapshot,result:{status:'completed',outputText:'READY'}})",context);
  // A subsequent user turn can reuse every ID except the native execution ID.
  context.snapshot={...context.snapshot,runId:"native-execution-2"};
  await vm.runInContext("hooks.beforeRun({snapshot})", context);
  context.call={...context.call,snapshot:context.snapshot};
  context.result={...context.result,snapshot:context.snapshot};
  await vm.runInContext("hooks.beforeTool(call)", context);
  await vm.runInContext("hooks.afterTool(result)", context);
  await vm.runInContext("hooks.afterRun({snapshot,result:{status:'completed',outputText:'READY'}})",context);
  context.snapshot={...context.snapshot,conversationId:"native-turn-2",runId:"native-execution-3"};
  await vm.runInContext("hooks.beforeRun({snapshot})", context);
  const observations=JSON.parse(JSON.stringify(context.observations));
  assert(observations.length>=6);
  assert(observations.every(x=>x.vesselCapture.rootSessionId==="native-root-1"));
  assert(observations.every(x=>x.vesselCapture.schema===2));
  assert(observations.at(-1).vesselCapture.conversationId==="native-turn-2");
  const post=observations.find(x=>x.hookName==="PostToolUse");
  assert.equal(post.vesselCapture.toolResult.output[0].exitCode,0);
  assert.equal(post.vesselCapture.toolResult.id,"call_0");
  const posts=observations.filter(x=>x.hookName==="PostToolUse").map(x=>x.vesselCapture);
  assert.equal(posts.length,2);
  assert.equal(posts[0].conversationId,posts[1].conversationId);
  assert.equal(posts[0].agentId,posts[1].agentId);
  assert.equal(posts[0].iteration,posts[1].iteration);
  assert.equal(posts[0].toolResult.id,posts[1].toolResult.id);
  assert.deepEqual(posts.map(x=>x.runId),["native-execution-1","native-execution-2"]);

  Object.assign(context,{
    oXh:x=>x,OUt:x=>x,l8u:300000,igr:()=>"keep",ij:class extends Error {},
  });
  vm.runInContext(between("async function sXh(", "function s8u("),context);
  function manager(details) {
    return {
      getOrCreateTerminal:async()=>({}),
      runCommand:()=>{
        const execution=new EventEmitter();
        execution.then=(resolve,reject)=>Promise.resolve().then(()=>{
          execution.emit("line","actual terminal fixture output");resolve();
        }).catch(reject);
        execution.getCompletionDetails=()=>details;
        return execution;
      },
    };
  }
  for (const code of [0,undefined]) {
    context.manager=manager({exitCode:code});
    const result=await vm.runInContext("sXh('probe','fixture-project',manager,1000)",context);
    const receipt=helper.commandResult("probe",result);
    assert.equal(receipt.exitCode,code===0?0:null);
    assert.equal(receipt.completed,code===0);
    assert.equal(receipt.result,"actual terminal fixture output");
  }
  for (const details of [{exitCode:3},{terminalClosed:true},{unobservedCommand:"unknown"}]) {
    context.manager=manager(details);
    await assert.rejects(()=>vm.runInContext("sXh('probe','fixture-project',manager,1000)",context));
  }
  console.log(JSON.stringify({
    patched_bundle_contract:"passed",hook_events:observations.length,
    protobuf_preserves_native_ids:true,session_binding_stable:true,
    native_execution_identity_preserved:true,
    observed_exit_and_unknown_outcome_checks:"passed",native_editor_test:"still_required",
  }));
})().catch(error=>{console.error(error);process.exitCode=1;});
