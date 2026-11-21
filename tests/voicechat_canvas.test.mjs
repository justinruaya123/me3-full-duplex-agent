import {test} from "node:test";
import assert from "node:assert/strict";
import {LiveCanvas} from "../integrations/voicechat/canvas.mjs";

const dashboard = {title:"Workshop", rows:[
  {kind:"option", label:"Morning", detail:"Room available"},
  {kind:"option", label:"Afternoon"},
  {kind:"task", label:"Reserve the room"}
]};
function delta(value) {
  return {type:"toolcall_delta",contentIndex:0,partial:{content:[
    {type:"toolCall",name:"show_dashboard",arguments:value}
  ]}};
}

test("Pi displays partial dashboard arguments and discards an unfinished revision", () => {
  const c = new LiveCanvas();
  c.save(dashboard);
  c.stream(delta({title:"Plan",rows:[{}]}));
  assert.match(c.lines().join("\n"),/Plan/);
  c.stream(delta({title:"Planning",rows:[{label:"New draft"}]}));
  assert.match(c.lines().join("\n"),/New draft/);
  c.cancel();
  assert.match(c.lines().join("\n"),/Workshop/);
  assert.doesNotMatch(c.lines().join("\n"),/New draft/);
});

test("voice actions select one option or check a task without changing other rows", () => {
  const c = new LiveCanvas();
  c.save(dashboard);
  c.change(1,"select");
  c.change(2,"select");
  c.change(3,"check");
  const restored = new LiveCanvas();
  restored.save(c.board);
  assert.deepEqual(restored.board.rows.map(r=>r.marked), [false,true,true]);
  assert.throws(()=>restored.change(2,"check"));
  assert.throws(()=>restored.change(4,"select"));
  restored.change(3,"uncheck");
  assert.equal(restored.board.rows[2].marked,false);
});

test("untrusted model content is bounded, terminal safe and scoped to the generative tool", () => {
  const c=new LiveCanvas();
  c.stream({type:"text_delta",delta:"secret"});
  assert.deepEqual(c.lines(),[]);
  c.stream(delta({title:"A\u001b[31m",rows:Array(20).fill({label:"x".repeat(10000)})}));
  assert.doesNotMatch(c.lines().join("\n"),/\u001b/);
  assert.ok(c.lines().length<=10);
  assert.ok(c.lines().join("\n").length<2500);
});
