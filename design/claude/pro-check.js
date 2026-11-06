var out=[],sizes={};
document.querySelectorAll("body *").forEach(function(e){
  if(e.closest("svg")) return;
  var s=getComputedStyle(e), r=e.getBoundingClientRect();
  var hasText=[].some.call(e.childNodes,function(c){return c.nodeType==3&&c.textContent.trim()});
  if(hasText){ sizes[s.fontSize]=(sizes[s.fontSize]||0)+1;
    if(r.right>1440.5||r.bottom>900.5) out.push("OFF "+e.textContent.slice(0,50));
    if(s.fontFamily.indexOf("serif")==0) out.push("SERIF");
  }
  if(e.scrollWidth>e.clientWidth+1&&s.overflow!="visible"&&e.clientWidth>0) out.push("CLIPW "+e.className+" "+e.textContent.slice(0,50)+" "+e.scrollWidth+">"+e.clientWidth);
  if(e.scrollHeight>e.clientHeight+1&&s.overflow!="visible"&&e.clientHeight>0) out.push("CLIPH "+e.className+" "+e.textContent.slice(0,40)+" "+e.scrollHeight+">"+e.clientHeight);
  if(hasText&&e.parentElement){var p=e.parentElement.getBoundingClientRect(); if(r.right>p.right+1&&s.display!="inline"&&e.parentElement.tagName!="BODY") out.push("OVER "+e.textContent.slice(0,40)+" "+Math.round(r.right)+">"+Math.round(p.right));}
});
out.push("sizes "+JSON.stringify(sizes));
document.body.innerHTML='<pre id="res">'+out.join("\n")+"</pre>";
