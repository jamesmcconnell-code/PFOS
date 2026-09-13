'use strict';
const fs = require('node:fs');
const path = require('node:path');
module.exports = {
  appId:'com.pfos.desktop', productName:'PFOS',
  directories:{output:'dist'},
  electronDist:path.join(__dirname,'node_modules/electron/dist'),
  asar:true,
  files:['entry.cjs','main.cjs','backend.cjs','frontend.cjs','maintenance.cjs',
    'policy.cjs','preload.cjs','storage.cjs','unavailable.html','assets/icon.png','package.json'],
  extraResources:[
    {from:'resources/backend',to:'backend'},
    {from:'resources/frontend',to:'frontend'},
  ],
  mac:{target:[{target:'dmg',arch:['x64']},{target:'zip',arch:['x64']}],
    category:'public.app-category.finance',icon:'assets/icon.png',identity:null},
  artifactName:'PFOS-${version}-mac-${arch}.${ext}',
  dmg:{title:'PFOS',contents:[{x:140,y:150},{x:420,y:150,type:'link',path:'/Applications'}]},
  beforePack:async context=>{
    const info=JSON.parse(fs.readFileSync(path.join(__dirname,'resources/backend/build-info.json')));
    if(process.platform!=='darwin' || process.arch!=='x64' || info.platform!=='darwin' || info.architecture!=='x86_64') {
      throw new Error('This release configuration requires a native Intel Mac backend and Electron build.');
    }
    for(const file of ['resources/frontend/login/index.html','resources/backend/pfos-api/pfos-api'])
      fs.accessSync(path.join(__dirname,file));
  },
};
