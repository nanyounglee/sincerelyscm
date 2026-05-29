const https = require('https');
const options = {
  hostname: 'api.airtable.com',
  path: '/v0/appkRWtF2j99XgBTq/tblUYmhOvtHGJ9NO3?maxRecords=1',
  headers: {
    'Authorization': 'Bearer patM0xqBHeF8WJIts'
  }
};
https.get(options, (res) => {
  let data = '';
  res.on('data', chunk => data += chunk);
  res.on('end', () => {
    console.log(data);
  });
});
