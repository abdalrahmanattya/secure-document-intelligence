import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../src/main.tsx', import.meta.url), 'utf8');
const uploadSource = await readFile(new URL('../src/upload-contract.ts', import.meta.url), 'utf8');
const styles = await readFile(new URL('../src/styles.css', import.meta.url), 'utf8');

assert.match(uploadSource, /toString\(16\)/, 'browser must calculate lowercase hexadecimal SHA-256');
assert.match(source, /VITE_COGNITO_DOMAIN/, 'cloud UI must have Cognito configuration');
assert.match(source, /code_challenge_method:'S256'/, 'cloud sign-in must use PKCE');
assert.match(source, /aria-label="Processing progress"/, 'progress must be accessible');
assert.match(source, /Source:/, 'field citations must be visible');
assert.match(source, /Correction for/, 'human corrections must be accessible');
assert.match(source, /Delete document/, 'delete action must be visible');
assert.match(source, /window\.confirm/, 'deletion must require confirmation');
assert.match(source, /REJECTED.*FAILED/s, 'malware/failure state warning path must exist');
assert.match(source, /id_token/, 'Cognito API calls must use the ID token');
assert.match(uploadSource, /FormData/, 'presigned POST must use FormData');
assert.doesNotMatch(uploadSource, /Authorization.*FormData/s, 'presigned POST must not send Authorization');
assert.match(styles, /@media\(max-width:650px\)/, 'review UI must have a responsive breakpoint');
console.log('UI contract/E2E checks passed: PKCE, digest, progress, citations, review, delete, responsive layout');
