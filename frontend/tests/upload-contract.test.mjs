import assert from 'node:assert/strict';
import {sha256Hex, uploadWithDescriptor} from '../src/upload-contract.ts';

const bytes = new TextEncoder().encode('hello world');
const file = new File([bytes], 'hello.txt', {type: 'text/plain'});
const digest = await sha256Hex(file);
assert.equal(digest, 'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9');

let localRequest;
const localResponse = await uploadWithDescriptor({method: 'PUT', url: '/v1/documents/local/content', headers: {'content-type': 'text/plain', 'x-upload-sha256': digest}, size: file.size, sha256: digest}, file, 'http://localhost:8000', '', async (url, init) => { localRequest = {url, init}; return new Response('{}', {status: 200}); });
assert.equal(localResponse.status, 200);
assert.equal(localRequest.url, 'http://localhost:8000/v1/documents/local/content');
assert.equal(localRequest.init.method, 'PUT');
assert.equal(localRequest.init.headers['x-upload-sha256'], digest);
assert.equal(await localRequest.init.body.text(), 'hello world');

let awsRequest;
const awsResponse = await uploadWithDescriptor({method: 'POST', url: 'https://s3.example.test/upload', fields: {key: 'tenant/document', Policy: 'signed'}, size: file.size, sha256: digest}, file, 'http://localhost:8000', 'must-not-be-sent', async (url, init) => { awsRequest = {url, init}; return new Response('', {status: 201}); });
assert.equal(awsResponse.status, 201);
assert.equal(awsRequest.url, 'https://s3.example.test/upload');
assert.equal(awsRequest.init.method, 'POST');
assert.equal(awsRequest.init.headers, undefined);
assert.equal(awsRequest.init.body.get('key'), 'tenant/document');
assert.equal(awsRequest.init.body.get('file').name, 'document');
console.log('Executable upload contract checks passed: known SHA-256, successful local PUT, presigned POST FormData');
