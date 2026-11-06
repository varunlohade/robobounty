var out=[];
document.querySelectorAll("body *").forEach(function(e){
  if(e.closest("svg")) return;
  var hasText=[].some.call(e.childNodes,function(c){return c.nodeType==3&&c.textContent.trim()});
  if(!hasText) return;
  var s=getComputedStyle(e), r=e.getBoundingClientRect();
  if(parseFloat(s.fontSize)<13) out.push("SMALL "+e.textContent.slice(0,40));
  if(r.right>1440||r.bottom>900) out.push("OFF "+e.textContent.slice(0,40)+" "+Math.round(r.right)+","+Math.round(r.bottom));
  if(e.scrollWidth>e.clientWidth+1&&s.display!="inline") out.push("WIDE "+e.textContent.slice(0,40)+" "+e.scrollWidth+">"+e.clientWidth);
});
document.body.innerHTML="<pre id=res>"+out.join("\n")+"</pre>";
