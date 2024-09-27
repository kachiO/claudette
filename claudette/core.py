# AUTOGENERATED! DO NOT EDIT! File to edit: ../00_core.ipynb.

# %% auto 0
__all__ = ['empty', 'models', 'models_aws', 'models_goog', 'find_block', 'contents', 'usage', 'mk_msgs', 'Client',
           'mk_tool_choice', 'call_func', 'mk_funcres', 'mk_toolres', 'Chat', 'img_msg', 'text_msg', 'mk_msg']

# %% ../00_core.ipynb
import inspect, typing, mimetypes, base64, json
from collections import abc
try: from IPython import display
except: display=None

from anthropic import Anthropic, AnthropicBedrock, AnthropicVertex
from anthropic.types import Usage, TextBlock, Message, ToolUseBlock
from anthropic.resources import messages

import toolslm
from toolslm.funccall import *

from fastcore import imghdr
from fastcore.meta import delegates
from fastcore.utils import *

# %% ../00_core.ipynb
empty = inspect.Parameter.empty

# %% ../00_core.ipynb
models = 'claude-3-opus-20240229','claude-3-5-sonnet-20240620','claude-3-haiku-20240307'

# %% ../00_core.ipynb
def find_block(r:abc.Mapping, # The message to look in
               blk_type:type=TextBlock  # The type of block to find
              ):
    "Find the first block of type `blk_type` in `r.content`."
    return first(o for o in r.content if isinstance(o,blk_type))

# %% ../00_core.ipynb
def contents(r):
    "Helper to get the contents from Claude response `r`."
    blk = find_block(r)
    if not blk and r.content: blk = r.content[0]
    return blk.text.strip() if hasattr(blk,'text') else str(blk)

# %% ../00_core.ipynb
@patch
def _repr_markdown_(self:(Message)):
    det = '\n- '.join(f'{k}: `{v}`' for k,v in self.model_dump().items())
    cts = re.sub(r'\$', '&#36;', contents(self))  # escape `$` for jupyter latex
    return f"""{cts}

<details>

- {det}

</details>"""

# %% ../00_core.ipynb
def usage(inp=0, # input tokens
          out=0,  # Output tokens
          cache_create=0, # Cache creation tokens
          cache_read=0 # Cache read tokens
         ):
    "Slightly more concise version of `Usage`."
    return Usage(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=cache_create, cache_read_input_tokens=cache_read)

# %% ../00_core.ipynb
@patch(as_prop=True)
def total(self:Usage): return self.input_tokens+self.output_tokens+getattr(self, "cache_creation_input_tokens",0)+getattr(self, "cache_read_input_tokens",0)

# %% ../00_core.ipynb
@patch
def __repr__(self:Usage): return f'In: {self.input_tokens}; Out: {self.output_tokens}; Cache create: {getattr(self, "cache_creation_input_tokens",0)}; Cache read: {getattr(self, "cache_read_input_tokens",0)}; Total: {self.total}'

# %% ../00_core.ipynb
@patch
def __add__(self:Usage, b):
    "Add together each of `input_tokens` and `output_tokens`"
    return usage(self.input_tokens+b.input_tokens, self.output_tokens+b.output_tokens, getattr(self,'cache_creation_input_tokens',0)+getattr(b,'cache_creation_input_tokens',0), getattr(self,'cache_read_input_tokens',0)+getattr(b,'cache_read_input_tokens',0))

# %% ../00_core.ipynb
def mk_msgs(msgs:list, **kw):
    "Helper to set 'assistant' role on alternate messages."
    if isinstance(msgs,str): msgs=[msgs]
    return [mk_msg(o, ('user','assistant')[i%2], **kw) for i,o in enumerate(msgs)]

# %% ../00_core.ipynb
class Client:
    def __init__(self, model, cli=None, log=False):
        "Basic Anthropic messages client."
        self.model,self.use = model,usage()
        self.log = [] if log else None
        self.c = (cli or Anthropic(default_headers={'anthropic-beta': 'prompt-caching-2024-07-31'}))

# %% ../00_core.ipynb
@patch
def _r(self:Client, r:Message, prefill=''):
    "Store the result of the message and accrue total usage."
    if prefill:
        blk = find_block(r)
        blk.text = prefill + (blk.text or '')
    self.result = r
    self.use += r.usage
    self.stop_reason = r.stop_reason
    self.stop_sequence = r.stop_sequence
    return r

# %% ../00_core.ipynb
@patch
def _log(self:Client, final, prefill, msgs, maxtok=None, sp=None, temp=None, stream=None, stop=None, **kwargs):
    self._r(final, prefill)
    if self.log is not None: self.log.append({
        "msgs": msgs, "prefill": prefill, **kwargs,
        "msgs": msgs, "prefill": prefill, "maxtok": maxtok, "sp": sp, "temp": temp, "stream": stream, "stop": stop, **kwargs,
        "result": self.result, "use": self.use, "stop_reason": self.stop_reason, "stop_sequence": self.stop_sequence
    })
    return self.result

# %% ../00_core.ipynb
@patch
def _stream(self:Client, msgs:list, prefill='', **kwargs):
    with self.c.messages.stream(model=self.model, messages=mk_msgs(msgs), **kwargs) as s:
        if prefill: yield(prefill)
        yield from s.text_stream
        self._log(s.get_final_message(), prefill, msgs, **kwargs)

# %% ../00_core.ipynb
@patch
def _precall(self:Client, msgs, prefill, stop, kwargs):
    pref = [prefill.strip()] if prefill else []
    if not isinstance(msgs,list): msgs = [msgs]
    if stop is not None:
        if not isinstance(stop, (list)): stop = [stop]
        kwargs["stop_sequences"] = stop
    msgs = mk_msgs(msgs+pref)
    return msgs

# %% ../00_core.ipynb
def mk_tool_choice(choose:Union[str,bool,None])->dict:
    "Create a `tool_choice` dict that's 'auto' if `choose` is `None`, 'any' if it is True, or 'tool' otherwise"
    return {"type": "tool", "name": choose} if isinstance(choose,str) else {'type':'any'} if choose else {'type':'auto'}

# %% ../00_core.ipynb
def _mk_ns(*funcs:list[callable]) -> dict[str,callable]:
    "Create a `dict` of name to function in `funcs`, to use as a namespace"
    return {f.__name__:f for f in funcs}

# %% ../00_core.ipynb
def call_func(fc:ToolUseBlock, # Tool use block from Claude's message
              ns:Optional[abc.Mapping]=None, # Namespace to search for tools, defaults to `globals()`
              obj:Optional=None # Object to search for tools
             ):
    "Call the function in the tool response `tr`, using namespace `ns`."
    if ns is None: ns=globals()
    if not isinstance(ns, abc.Mapping): ns = _mk_ns(*ns)
    func = getattr(obj, fc.name, None)
    if not func: func = ns[fc.name]
    res = func(**fc.input)
    return res

def mk_funcres(tuid, res):
    "Given tool use id and the tool result, create a tool_result response."
    return dict(type="tool_result", tool_use_id=tuid, content=res)

# %% ../00_core.ipynb
def mk_toolres(
    r:abc.Mapping, # Tool use request response from Claude
    ns:Optional[abc.Mapping]=None, # Namespace to search for tools
    obj:Optional=None # Class to search for tools
    ):
    "Create a `tool_result` message from response `r`."
    cts = getattr(r, 'content', [])
    res = [mk_msg(r)]
    tcs = [mk_funcres(o.id, call_func(o, ns=ns, obj=obj)) for o in cts if isinstance(o,ToolUseBlock)]
    if tcs: res.append(mk_msg(tcs))
    return res

# %% ../00_core.ipynb
@patch
@delegates(messages.Messages.create)
def __call__(self:Client,
             msgs:list, # List of messages in the dialog
             sp='', # The system prompt
             temp=0, # Temperature
             maxtok=4096, # Maximum tokens
             prefill='', # Optional prefill to pass to Claude as start of its response
             stream:bool=False, # Stream response?
             stop=None, # Stop sequence
             tools:Optional[list]=None, # List of tools to make available to Claude
             tool_choice:Optional[dict]=None, # Optionally force use of some tool
             **kwargs):
    "Make a call to Claude."
    if tools: kwargs['tools'] = [get_schema(o) for o in listify(tools)]
    if tool_choice and pr: kwargs['tool_choice'] = mk_tool_choice(tool_choice)
    msgs = self._precall(msgs, prefill, stop, kwargs)
    if stream: return self._stream(msgs, prefill=prefill, max_tokens=maxtok, system=sp, temperature=temp, **kwargs)
    res = self.c.messages.create(model=self.model, messages=msgs, max_tokens=maxtok, system=sp, temperature=temp, **kwargs)
    return self._log(res, prefill, msgs, maxtok, sp, temp, stream=stream, stop=stop, **kwargs)

# %% ../00_core.ipynb
@patch
@delegates(Client.__call__)
def structured(self:Client,
               msgs:list, # List of messages in the dialog
               ns:Optional[abc.Mapping]=None, # Namespace to search for tools
               obj:Optional=None, # Class to search for tools
               **kwargs):
    "Return the value of all tool calls (generally used for structured outputs)"
    res = self(msgs, **kwargs)
    if ns is None: ns=globals()
    cts = getattr(r, 'content', [])
    tcs = [call_func(o, ns=ns, obj=obj) for o in cts if isinstance(o,ToolUseBlock)]
    return tcs

# %% ../00_core.ipynb
class Chat:
    def __init__(self,
                 model:Optional[str]=None, # Model to use (leave empty if passing `cli`)
                 cli:Optional[Client]=None, # Client to use (leave empty if passing `model`)
                 sp='', # Optional system prompt
                 tools:Optional[list]=None, # List of tools to make available to Claude
                 cont_pr:Optional[str]=None, # User prompt to continue an assistant response: assistant,[user:"..."],assistant
                 tool_choice:Optional[dict]=None): # Optionally force use of some tool
        "Anthropic chat client."
        assert model or cli
        assert cont_pr != "", "cont_pr may not be an empty string"
        self.c = (cli or Client(model))
        self.h,self.sp,self.tools,self.cont_pr,self.tool_choice = [],sp,tools,cont_pr,tool_choice

    @property
    def use(self): return self.c.use

# %% ../00_core.ipynb
@patch
def _stream(self:Chat, res):
    yield from res
    self.h += mk_toolres(self.c.result, ns=self.tools, obj=self)

# %% ../00_core.ipynb
@patch
def _post_pr(self:Chat, pr, prev_role):
    if pr is None and prev_role == 'assistant':
        if self.cont_pr is None:
            raise ValueError("Prompt must be given after assistant completion, or use `self.cont_pr`.")
        pr = self.cont_pr # No user prompt, keep the chain
    if pr: self.h.append(mk_msg(pr))

# %% ../00_core.ipynb
@patch
def _append_pr(self:Chat,
               pr=None,  # Prompt / message
              ):
    prev_role = nested_idx(self.h, -1, 'role') if self.h else 'assistant' # First message should be 'user'
    if pr and prev_role == 'user': self() # already user request pending
    self._post_pr(pr, prev_role)

# %% ../00_core.ipynb
@patch
def __call__(self:Chat,
             pr=None,  # Prompt / message
             temp=0, # Temperature
             maxtok=4096, # Maximum tokens
             stream=False, # Stream response?
             prefill='', # Optional prefill to pass to Claude as start of its response
             **kw):
    self._append_pr(pr)
    res = self.c(self.h, stream=stream, prefill=prefill, sp=self.sp, temp=temp, maxtok=maxtok,
                 tools=self.tools, tool_choice=self.tool_choice, **kw)
    if stream: return self._stream(res)
    self.h += mk_toolres(self.c.result, ns=self.tools, obj=self)
    return res

# %% ../00_core.ipynb
def _add_cache(d, cache):
    "Optionally add cache control"
    if cache: d["cache_control"] = {"type": "ephemeral"}
    return d

# %% ../00_core.ipynb
def img_msg(data:bytes, cache=False)->dict:
    "Convert image `data` into an encoded `dict`"
    img = base64.b64encode(data).decode("utf-8")
    mtype = mimetypes.types_map['.'+imghdr.what(None, h=data)]
    r = dict(type="base64", media_type=mtype, data=img)
    return _add_cache({"type": "image", "source": r}, cache)

# %% ../00_core.ipynb
def text_msg(s:str, cache=False)->dict:
    "Convert `s` to a text message"
    return _add_cache({"type": "text", "text": s}, cache)

# %% ../00_core.ipynb
def _str_if_needed(o):
    if isinstance(o, (list,tuple,abc.Mapping)) or hasattr(o, '__pydantic_serializer__'): return o
    return str(o)

# %% ../00_core.ipynb
def _mk_content(src, cache=False):
    "Create appropriate content data structure based on type of content"
    if isinstance(src,str): return text_msg(src, cache=cache)
    if isinstance(src,bytes): return img_msg(src, cache=cache)
    if isinstance(src, abc.Mapping): return {k:_str_if_needed(v) for k,v in src.items()}
    return _str_if_needed(src)

# %% ../00_core.ipynb
def mk_msg(content, # A string, list, or dict containing the contents of the message
           role='user', # Must be 'user' or 'assistant'
           cache=False,
           **kw):
    "Helper to create a `dict` appropriate for a Claude message. `kw` are added as key/value pairs to the message"
    if hasattr(content, 'content'): content,role = content.content,content.role
    if isinstance(content, abc.Mapping): content=content.get('content', content)
    if not isinstance(content, list): content=[content]
    content = [_mk_content(o, cache if islast else False) for islast,o in loop_last(content)] if content else '.'
    return dict(role=role, content=content, **kw)

# %% ../00_core.ipynb
models_aws = ('anthropic.claude-3-haiku-20240307-v1:0', 'anthropic.claude-3-sonnet-20240229-v1:0',
    'anthropic.claude-3-opus-20240229-v1:0', 'anthropic.claude-3-5-sonnet-20240620-v1:0')

# %% ../00_core.ipynb
models_goog = 'claude-3-haiku@20240307', 'claude-3-sonnet@20240229', 'claude-3-opus@20240229', 'claude-3-5-sonnet@20240620'
