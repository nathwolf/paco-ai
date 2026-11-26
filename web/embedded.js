'use strict';
if(new URLSearchParams(location.search).has('embedded')){
 document.body.classList.add('embedded');
 if(location.pathname==='/controls'){
  for(const section of [...document.querySelectorAll('main>section')]){
   const heading=section.querySelector('h2');if(!heading||section.classList.contains('last'))continue;
   if(heading.textContent.includes('More of Paco')){section.hidden=true;continue;}
   const group=document.createElement('details'),summary=document.createElement('summary');group.className='control-group';summary.textContent=[...heading.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim()||heading.textContent.trim();section.before(group);group.append(summary,section);
  }
 }
 document.querySelectorAll('a[href="/"],a[href="/meetings"]').forEach(a=>a.onclick=e=>{e.preventDefault();parent.postMessage({paco:'navigate',tab:a.getAttribute('href')==='/meetings'?'meetings':'tasks'},location.origin);});
}
