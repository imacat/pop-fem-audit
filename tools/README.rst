=======================================
Tools for A Feminist Audit of Pop Music
=======================================


Description
===========

This is a collection of supporting tools for the conference paper "流行音樂中「女性力量」語彙的挪用與污染——以 Billboard Year-End Hot 100（2016–2025）為例的內容分析".


Installation
============

Use ``pip`` to install these tools.

::

    % pip install .

This will install the ``pop-fem-audit-tools`` script in the Python environment.


Usage
=====

::

    % pop-fem-audit-tools {command} [options] [arguments]

Runs a specific tool command, where "command" can be:


run-llm
-------

A general command that runs specific LLM instructions with the Anthropic API.  The API key must be present in the ``.env`` file in the working directory.  Check ``pop-fem-audit-tools run-llm -h`` for complete instructions on its usage.


Copyright
=========

 Copyright (c) 2026 imacat.

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.


Authors
=======

| imacat
| imacat@mail.imacat.idv.tw
| 2026/7/31
