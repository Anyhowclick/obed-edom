#!/usr/bin/env osascript -l JavaScript
// Which writes actually set a vertical rule's geometry?
//
// The remap sends width, height, startPoint, endPoint and position in that
// order, and a 383-long vertical rule comes out 1 long and horizontal. Try each
// write on its own line object and read the result back.
'use strict';

function run() {
  const app = Application('com.apple.Keynote');
  app.includeStandardAdditions = true;
  const doc = app.Document().make();
  const slide = doc.slides[0];
  const out = { version: app.version(), cases: [] };

  function makeLine() {
    // A vertical rule, the shape the divider actually is.
    const line = app.Line({ startPoint: [200, 800], endPoint: [200, 200] });
    slide.lines.push(line);
    return line;
  }

  function read(line) {
    const o = {};
    for (const k of ['width', 'height']) {
      try {
        o[k] = Number(line[k]());
      } catch (e) {
        o[k] = 'err';
      }
    }
    for (const k of ['startPoint', 'endPoint', 'position']) {
      try {
        const p = line[k]();
        o[k] = [Number(p[0]), Number(p[1])];
      } catch (e) {
        o[k] = 'err';
      }
    }
    return o;
  }

  function attempt(name, apply) {
    const line = makeLine();
    const before = read(line);
    let error = null;
    try {
      apply(line);
    } catch (e) {
      error = e.message;
    }
    out.cases.push({ name: name, before: before, after: read(line), error: error });
  }

  attempt('baseline (no writes)', function () {});
  attempt('width=383 only', function (l) {
    l.width = 383;
  });
  attempt('height=0 only', function (l) {
    l.height = 0;
  });
  attempt('width=383 then height=0', function (l) {
    l.width = 383;
    l.height = 0;
  });
  attempt('endpoints only', function (l) {
    l.startPoint = [480, 1004];
    l.endPoint = [480, 621];
  });
  attempt('current order: w,h,start,end,position', function (l) {
    l.width = 383;
    l.height = 0;
    l.startPoint = [480, 1004];
    l.endPoint = [480, 621];
    l.position = [480, 621];
  });
  attempt('endpoints then position', function (l) {
    l.startPoint = [480, 1004];
    l.endPoint = [480, 621];
    l.position = [480, 621];
  });
  attempt('width only then position', function (l) {
    l.width = 383;
    l.position = [480, 621];
  });

  doc.close({ saving: 'no' });
  return JSON.stringify(out, null, 2);
}
