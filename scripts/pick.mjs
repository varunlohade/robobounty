import load from '@mujoco/mujoco';
import fs from 'node:fs';
const mj = await load();
const m = mj.MjModel.from_xml_string(fs.readFileSync('public/robots/acme-arm.xml','utf8'));
const d = new mj.MjData(m);
const L1=0.25, L2=0.22, WR=0.07, SH=[0.15,0,0.51];
function ik([x,y,z]){
  const yaw=Math.atan2(y-SH[1],x-SH[0]);
  const r=Math.hypot(x-SH[0],y-SH[1]), h=z+WR-SH[2];
  let D=(r*r+h*h-L1*L1-L2*L2)/(2*L1*L2); D=Math.max(-1,Math.min(1,D));
  const t2=Math.acos(D);
  const t1=Math.atan2(r,h)-Math.atan2(L2*Math.sin(t2),L1+L2*Math.cos(t2));
  return [yaw,t1,t2,Math.PI-t1-t2];
}
const cid=mj.mj_name2id(m,mj.mjtObj.mjOBJ_BODY.value,'cube');
const cube=()=>Array.from(d.xpos.slice(cid*3,cid*3+3));
const grip=()=>Array.from(d.site_xpos.slice(0,3));
const f=v=>v.map(x=>x.toFixed(3)).join(',');
let cur=null;
function go(p,g,sec){const a=cur||grip();const n=Math.round(sec/0.002);const move=Math.round(n*0.7);
 for(let i=0;i<n;i++){const t=Math.min(1,i/move), s=t*t*(3-2*t);
  const q=ik([0,1,2].map(k=>a[k]+(p[k]-a[k])*s));
  d.ctrl[0]=q[0];d.ctrl[1]=q[1];d.ctrl[2]=q[2];d.ctrl[3]=q[3];d.ctrl[4]=g;mj.mj_step(m,d);} cur=p;}
mj.mj_forward(m,d);
const c0=cube(), OPEN=0.035, SHUT=0;
const plan=[["home",[0.3,0,0.75],OPEN,1.0],["above cube",[c0[0],c0[1],c0[2]+0.12],OPEN,1.5],["down",[c0[0],c0[1],c0[2]+0.005],OPEN,1.2],["grip",[c0[0],c0[1],c0[2]+0.005],SHUT,0.8],["lift",[c0[0],c0[1],c0[2]+0.18],SHUT,1.2],["over shelf",[0.45,0.28,0.54+0.025+0.12],SHUT,1.5],["lower",[0.45,0.28,0.54+0.03],SHUT,1.0],["release",[0.45,0.28,0.54+0.03],OPEN,0.6],["retreat",[0.45,0.28,0.75],OPEN,1.0]];
for(const [n,p,g,s] of plan){go(p,g,s);console.log(n.padEnd(11),'grip',f(grip()),'cube',f(cube()));}
const c=cube(); const q=Array.from(d.xquat.slice(cid*4,cid*4+4));
const upright=Math.abs(1-2*(q[1]*q[1]+q[2]*q[2]))>0.95;
console.log('ON SHELF:', Math.abs(c[0]-0.45)<0.1&&Math.abs(c[1]-0.28)<0.1&&c[2]>0.55, 'upright', upright);
