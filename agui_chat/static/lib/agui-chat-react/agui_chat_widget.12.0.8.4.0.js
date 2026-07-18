var AguiChatReactBundle = function(exports) {
  "use strict";var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);

  function _mergeNamespaces(n, m) {
    for (var i = 0; i < m.length; i++) {
      const e = m[i];
      if (typeof e !== "string" && !Array.isArray(e)) {
        for (const k in e) {
          if (k !== "default" && !(k in n)) {
            const d = Object.getOwnPropertyDescriptor(e, k);
            if (d) {
              Object.defineProperty(n, k, d.get ? d : {
                enumerable: true,
                get: () => e[k]
              });
            }
          }
        }
      }
    }
    return Object.freeze(Object.defineProperty(n, Symbol.toStringTag, { value: "Module" }));
  }
  function getDefaultExportFromCjs(x) {
    return x && x.__esModule && Object.prototype.hasOwnProperty.call(x, "default") ? x["default"] : x;
  }
  var jsxRuntime$1 = { exports: {} };
  var reactJsxRuntime_production_min = {};
  var react = { exports: {} };
  var react_production_min = {};
  /**
   * @license React
   * react.production.min.js
   *
   * Copyright (c) Facebook, Inc. and its affiliates.
   *
   * This source code is licensed under the MIT license found in the
   * LICENSE file in the root directory of this source tree.
   */
  var hasRequiredReact_production_min;
  function requireReact_production_min() {
    if (hasRequiredReact_production_min) return react_production_min;
    hasRequiredReact_production_min = 1;
    var l = Symbol.for("react.element"), n = Symbol.for("react.portal"), p = Symbol.for("react.fragment"), q = Symbol.for("react.strict_mode"), r2 = Symbol.for("react.profiler"), t = Symbol.for("react.provider"), u = Symbol.for("react.context"), v = Symbol.for("react.forward_ref"), w = Symbol.for("react.suspense"), x = Symbol.for("react.memo"), y = Symbol.for("react.lazy"), z = Symbol.iterator;
    function A(a) {
      if (null === a || "object" !== typeof a) return null;
      a = z && a[z] || a["@@iterator"];
      return "function" === typeof a ? a : null;
    }
    var B = { isMounted: function() {
      return false;
    }, enqueueForceUpdate: function() {
    }, enqueueReplaceState: function() {
    }, enqueueSetState: function() {
    } }, C = Object.assign, D = {};
    function E(a, b, e) {
      this.props = a;
      this.context = b;
      this.refs = D;
      this.updater = e || B;
    }
    E.prototype.isReactComponent = {};
    E.prototype.setState = function(a, b) {
      if ("object" !== typeof a && "function" !== typeof a && null != a) throw Error("setState(...): takes an object of state variables to update or a function which returns an object of state variables.");
      this.updater.enqueueSetState(this, a, b, "setState");
    };
    E.prototype.forceUpdate = function(a) {
      this.updater.enqueueForceUpdate(this, a, "forceUpdate");
    };
    function F() {
    }
    F.prototype = E.prototype;
    function G(a, b, e) {
      this.props = a;
      this.context = b;
      this.refs = D;
      this.updater = e || B;
    }
    var H = G.prototype = new F();
    H.constructor = G;
    C(H, E.prototype);
    H.isPureReactComponent = true;
    var I = Array.isArray, J = Object.prototype.hasOwnProperty, K = { current: null }, L = { key: true, ref: true, __self: true, __source: true };
    function M(a, b, e) {
      var d, c = {}, k = null, h = null;
      if (null != b) for (d in void 0 !== b.ref && (h = b.ref), void 0 !== b.key && (k = "" + b.key), b) J.call(b, d) && !L.hasOwnProperty(d) && (c[d] = b[d]);
      var g = arguments.length - 2;
      if (1 === g) c.children = e;
      else if (1 < g) {
        for (var f = Array(g), m = 0; m < g; m++) f[m] = arguments[m + 2];
        c.children = f;
      }
      if (a && a.defaultProps) for (d in g = a.defaultProps, g) void 0 === c[d] && (c[d] = g[d]);
      return { $$typeof: l, type: a, key: k, ref: h, props: c, _owner: K.current };
    }
    function N(a, b) {
      return { $$typeof: l, type: a.type, key: b, ref: a.ref, props: a.props, _owner: a._owner };
    }
    function O(a) {
      return "object" === typeof a && null !== a && a.$$typeof === l;
    }
    function escape(a) {
      var b = { "=": "=0", ":": "=2" };
      return "$" + a.replace(/[=:]/g, function(a2) {
        return b[a2];
      });
    }
    var P = /\/+/g;
    function Q(a, b) {
      return "object" === typeof a && null !== a && null != a.key ? escape("" + a.key) : b.toString(36);
    }
    function R(a, b, e, d, c) {
      var k = typeof a;
      if ("undefined" === k || "boolean" === k) a = null;
      var h = false;
      if (null === a) h = true;
      else switch (k) {
        case "string":
        case "number":
          h = true;
          break;
        case "object":
          switch (a.$$typeof) {
            case l:
            case n:
              h = true;
          }
      }
      if (h) return h = a, c = c(h), a = "" === d ? "." + Q(h, 0) : d, I(c) ? (e = "", null != a && (e = a.replace(P, "$&/") + "/"), R(c, b, e, "", function(a2) {
        return a2;
      })) : null != c && (O(c) && (c = N(c, e + (!c.key || h && h.key === c.key ? "" : ("" + c.key).replace(P, "$&/") + "/") + a)), b.push(c)), 1;
      h = 0;
      d = "" === d ? "." : d + ":";
      if (I(a)) for (var g = 0; g < a.length; g++) {
        k = a[g];
        var f = d + Q(k, g);
        h += R(k, b, e, f, c);
      }
      else if (f = A(a), "function" === typeof f) for (a = f.call(a), g = 0; !(k = a.next()).done; ) k = k.value, f = d + Q(k, g++), h += R(k, b, e, f, c);
      else if ("object" === k) throw b = String(a), Error("Objects are not valid as a React child (found: " + ("[object Object]" === b ? "object with keys {" + Object.keys(a).join(", ") + "}" : b) + "). If you meant to render a collection of children, use an array instead.");
      return h;
    }
    function S(a, b, e) {
      if (null == a) return a;
      var d = [], c = 0;
      R(a, d, "", "", function(a2) {
        return b.call(e, a2, c++);
      });
      return d;
    }
    function T(a) {
      if (-1 === a._status) {
        var b = a._result;
        b = b();
        b.then(function(b2) {
          if (0 === a._status || -1 === a._status) a._status = 1, a._result = b2;
        }, function(b2) {
          if (0 === a._status || -1 === a._status) a._status = 2, a._result = b2;
        });
        -1 === a._status && (a._status = 0, a._result = b);
      }
      if (1 === a._status) return a._result.default;
      throw a._result;
    }
    var U = { current: null }, V = { transition: null }, W = { ReactCurrentDispatcher: U, ReactCurrentBatchConfig: V, ReactCurrentOwner: K };
    function X2() {
      throw Error("act(...) is not supported in production builds of React.");
    }
    react_production_min.Children = { map: S, forEach: function(a, b, e) {
      S(a, function() {
        b.apply(this, arguments);
      }, e);
    }, count: function(a) {
      var b = 0;
      S(a, function() {
        b++;
      });
      return b;
    }, toArray: function(a) {
      return S(a, function(a2) {
        return a2;
      }) || [];
    }, only: function(a) {
      if (!O(a)) throw Error("React.Children.only expected to receive a single React element child.");
      return a;
    } };
    react_production_min.Component = E;
    react_production_min.Fragment = p;
    react_production_min.Profiler = r2;
    react_production_min.PureComponent = G;
    react_production_min.StrictMode = q;
    react_production_min.Suspense = w;
    react_production_min.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED = W;
    react_production_min.act = X2;
    react_production_min.cloneElement = function(a, b, e) {
      if (null === a || void 0 === a) throw Error("React.cloneElement(...): The argument must be a React element, but you passed " + a + ".");
      var d = C({}, a.props), c = a.key, k = a.ref, h = a._owner;
      if (null != b) {
        void 0 !== b.ref && (k = b.ref, h = K.current);
        void 0 !== b.key && (c = "" + b.key);
        if (a.type && a.type.defaultProps) var g = a.type.defaultProps;
        for (f in b) J.call(b, f) && !L.hasOwnProperty(f) && (d[f] = void 0 === b[f] && void 0 !== g ? g[f] : b[f]);
      }
      var f = arguments.length - 2;
      if (1 === f) d.children = e;
      else if (1 < f) {
        g = Array(f);
        for (var m = 0; m < f; m++) g[m] = arguments[m + 2];
        d.children = g;
      }
      return { $$typeof: l, type: a.type, key: c, ref: k, props: d, _owner: h };
    };
    react_production_min.createContext = function(a) {
      a = { $$typeof: u, _currentValue: a, _currentValue2: a, _threadCount: 0, Provider: null, Consumer: null, _defaultValue: null, _globalName: null };
      a.Provider = { $$typeof: t, _context: a };
      return a.Consumer = a;
    };
    react_production_min.createElement = M;
    react_production_min.createFactory = function(a) {
      var b = M.bind(null, a);
      b.type = a;
      return b;
    };
    react_production_min.createRef = function() {
      return { current: null };
    };
    react_production_min.forwardRef = function(a) {
      return { $$typeof: v, render: a };
    };
    react_production_min.isValidElement = O;
    react_production_min.lazy = function(a) {
      return { $$typeof: y, _payload: { _status: -1, _result: a }, _init: T };
    };
    react_production_min.memo = function(a, b) {
      return { $$typeof: x, type: a, compare: void 0 === b ? null : b };
    };
    react_production_min.startTransition = function(a) {
      var b = V.transition;
      V.transition = {};
      try {
        a();
      } finally {
        V.transition = b;
      }
    };
    react_production_min.unstable_act = X2;
    react_production_min.useCallback = function(a, b) {
      return U.current.useCallback(a, b);
    };
    react_production_min.useContext = function(a) {
      return U.current.useContext(a);
    };
    react_production_min.useDebugValue = function() {
    };
    react_production_min.useDeferredValue = function(a) {
      return U.current.useDeferredValue(a);
    };
    react_production_min.useEffect = function(a, b) {
      return U.current.useEffect(a, b);
    };
    react_production_min.useId = function() {
      return U.current.useId();
    };
    react_production_min.useImperativeHandle = function(a, b, e) {
      return U.current.useImperativeHandle(a, b, e);
    };
    react_production_min.useInsertionEffect = function(a, b) {
      return U.current.useInsertionEffect(a, b);
    };
    react_production_min.useLayoutEffect = function(a, b) {
      return U.current.useLayoutEffect(a, b);
    };
    react_production_min.useMemo = function(a, b) {
      return U.current.useMemo(a, b);
    };
    react_production_min.useReducer = function(a, b, e) {
      return U.current.useReducer(a, b, e);
    };
    react_production_min.useRef = function(a) {
      return U.current.useRef(a);
    };
    react_production_min.useState = function(a) {
      return U.current.useState(a);
    };
    react_production_min.useSyncExternalStore = function(a, b, e) {
      return U.current.useSyncExternalStore(a, b, e);
    };
    react_production_min.useTransition = function() {
      return U.current.useTransition();
    };
    react_production_min.version = "18.3.1";
    return react_production_min;
  }
  var hasRequiredReact;
  function requireReact() {
    if (hasRequiredReact) return react.exports;
    hasRequiredReact = 1;
    {
      react.exports = requireReact_production_min();
    }
    return react.exports;
  }
  /**
   * @license React
   * react-jsx-runtime.production.min.js
   *
   * Copyright (c) Facebook, Inc. and its affiliates.
   *
   * This source code is licensed under the MIT license found in the
   * LICENSE file in the root directory of this source tree.
   */
  var hasRequiredReactJsxRuntime_production_min;
  function requireReactJsxRuntime_production_min() {
    if (hasRequiredReactJsxRuntime_production_min) return reactJsxRuntime_production_min;
    hasRequiredReactJsxRuntime_production_min = 1;
    var f = requireReact(), k = Symbol.for("react.element"), l = Symbol.for("react.fragment"), m = Object.prototype.hasOwnProperty, n = f.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentOwner, p = { key: true, ref: true, __self: true, __source: true };
    function q(c, a, g) {
      var b, d = {}, e = null, h = null;
      void 0 !== g && (e = "" + g);
      void 0 !== a.key && (e = "" + a.key);
      void 0 !== a.ref && (h = a.ref);
      for (b in a) m.call(a, b) && !p.hasOwnProperty(b) && (d[b] = a[b]);
      if (c && c.defaultProps) for (b in a = c.defaultProps, a) void 0 === d[b] && (d[b] = a[b]);
      return { $$typeof: k, type: c, key: e, ref: h, props: d, _owner: n.current };
    }
    reactJsxRuntime_production_min.Fragment = l;
    reactJsxRuntime_production_min.jsx = q;
    reactJsxRuntime_production_min.jsxs = q;
    return reactJsxRuntime_production_min;
  }
  var hasRequiredJsxRuntime;
  function requireJsxRuntime() {
    if (hasRequiredJsxRuntime) return jsxRuntime$1.exports;
    hasRequiredJsxRuntime = 1;
    {
      jsxRuntime$1.exports = requireReactJsxRuntime_production_min();
    }
    return jsxRuntime$1.exports;
  }
  var jsxRuntimeExports = requireJsxRuntime();
  const jsxRuntime = /* @__PURE__ */ getDefaultExportFromCjs(jsxRuntimeExports);
  const ReactJSXRuntime = /* @__PURE__ */ _mergeNamespaces({
    __proto__: null,
    default: jsxRuntime
  }, [jsxRuntimeExports]);
  var reactExports = requireReact();
  const React = /* @__PURE__ */ getDefaultExportFromCjs(reactExports);
  var client = {};
  var reactDom = { exports: {} };
  var reactDom_production_min = {};
  var scheduler = { exports: {} };
  var scheduler_production_min = {};
  /**
   * @license React
   * scheduler.production.min.js
   *
   * Copyright (c) Facebook, Inc. and its affiliates.
   *
   * This source code is licensed under the MIT license found in the
   * LICENSE file in the root directory of this source tree.
   */
  var hasRequiredScheduler_production_min;
  function requireScheduler_production_min() {
    if (hasRequiredScheduler_production_min) return scheduler_production_min;
    hasRequiredScheduler_production_min = 1;
    (function(exports2) {
      function f(a, b) {
        var c = a.length;
        a.push(b);
        a: for (; 0 < c; ) {
          var d = c - 1 >>> 1, e = a[d];
          if (0 < g(e, b)) a[d] = b, a[c] = e, c = d;
          else break a;
        }
      }
      function h(a) {
        return 0 === a.length ? null : a[0];
      }
      function k(a) {
        if (0 === a.length) return null;
        var b = a[0], c = a.pop();
        if (c !== b) {
          a[0] = c;
          a: for (var d = 0, e = a.length, w = e >>> 1; d < w; ) {
            var m = 2 * (d + 1) - 1, C = a[m], n = m + 1, x = a[n];
            if (0 > g(C, c)) n < e && 0 > g(x, C) ? (a[d] = x, a[n] = c, d = n) : (a[d] = C, a[m] = c, d = m);
            else if (n < e && 0 > g(x, c)) a[d] = x, a[n] = c, d = n;
            else break a;
          }
        }
        return b;
      }
      function g(a, b) {
        var c = a.sortIndex - b.sortIndex;
        return 0 !== c ? c : a.id - b.id;
      }
      if ("object" === typeof performance && "function" === typeof performance.now) {
        var l = performance;
        exports2.unstable_now = function() {
          return l.now();
        };
      } else {
        var p = Date, q = p.now();
        exports2.unstable_now = function() {
          return p.now() - q;
        };
      }
      var r2 = [], t = [], u = 1, v = null, y = 3, z = false, A = false, B = false, D = "function" === typeof setTimeout ? setTimeout : null, E = "function" === typeof clearTimeout ? clearTimeout : null, F = "undefined" !== typeof setImmediate ? setImmediate : null;
      "undefined" !== typeof navigator && void 0 !== navigator.scheduling && void 0 !== navigator.scheduling.isInputPending && navigator.scheduling.isInputPending.bind(navigator.scheduling);
      function G(a) {
        for (var b = h(t); null !== b; ) {
          if (null === b.callback) k(t);
          else if (b.startTime <= a) k(t), b.sortIndex = b.expirationTime, f(r2, b);
          else break;
          b = h(t);
        }
      }
      function H(a) {
        B = false;
        G(a);
        if (!A) if (null !== h(r2)) A = true, I(J);
        else {
          var b = h(t);
          null !== b && K(H, b.startTime - a);
        }
      }
      function J(a, b) {
        A = false;
        B && (B = false, E(L), L = -1);
        z = true;
        var c = y;
        try {
          G(b);
          for (v = h(r2); null !== v && (!(v.expirationTime > b) || a && !M()); ) {
            var d = v.callback;
            if ("function" === typeof d) {
              v.callback = null;
              y = v.priorityLevel;
              var e = d(v.expirationTime <= b);
              b = exports2.unstable_now();
              "function" === typeof e ? v.callback = e : v === h(r2) && k(r2);
              G(b);
            } else k(r2);
            v = h(r2);
          }
          if (null !== v) var w = true;
          else {
            var m = h(t);
            null !== m && K(H, m.startTime - b);
            w = false;
          }
          return w;
        } finally {
          v = null, y = c, z = false;
        }
      }
      var N = false, O = null, L = -1, P = 5, Q = -1;
      function M() {
        return exports2.unstable_now() - Q < P ? false : true;
      }
      function R() {
        if (null !== O) {
          var a = exports2.unstable_now();
          Q = a;
          var b = true;
          try {
            b = O(true, a);
          } finally {
            b ? S() : (N = false, O = null);
          }
        } else N = false;
      }
      var S;
      if ("function" === typeof F) S = function() {
        F(R);
      };
      else if ("undefined" !== typeof MessageChannel) {
        var T = new MessageChannel(), U = T.port2;
        T.port1.onmessage = R;
        S = function() {
          U.postMessage(null);
        };
      } else S = function() {
        D(R, 0);
      };
      function I(a) {
        O = a;
        N || (N = true, S());
      }
      function K(a, b) {
        L = D(function() {
          a(exports2.unstable_now());
        }, b);
      }
      exports2.unstable_IdlePriority = 5;
      exports2.unstable_ImmediatePriority = 1;
      exports2.unstable_LowPriority = 4;
      exports2.unstable_NormalPriority = 3;
      exports2.unstable_Profiling = null;
      exports2.unstable_UserBlockingPriority = 2;
      exports2.unstable_cancelCallback = function(a) {
        a.callback = null;
      };
      exports2.unstable_continueExecution = function() {
        A || z || (A = true, I(J));
      };
      exports2.unstable_forceFrameRate = function(a) {
        0 > a || 125 < a ? console.error("forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported") : P = 0 < a ? Math.floor(1e3 / a) : 5;
      };
      exports2.unstable_getCurrentPriorityLevel = function() {
        return y;
      };
      exports2.unstable_getFirstCallbackNode = function() {
        return h(r2);
      };
      exports2.unstable_next = function(a) {
        switch (y) {
          case 1:
          case 2:
          case 3:
            var b = 3;
            break;
          default:
            b = y;
        }
        var c = y;
        y = b;
        try {
          return a();
        } finally {
          y = c;
        }
      };
      exports2.unstable_pauseExecution = function() {
      };
      exports2.unstable_requestPaint = function() {
      };
      exports2.unstable_runWithPriority = function(a, b) {
        switch (a) {
          case 1:
          case 2:
          case 3:
          case 4:
          case 5:
            break;
          default:
            a = 3;
        }
        var c = y;
        y = a;
        try {
          return b();
        } finally {
          y = c;
        }
      };
      exports2.unstable_scheduleCallback = function(a, b, c) {
        var d = exports2.unstable_now();
        "object" === typeof c && null !== c ? (c = c.delay, c = "number" === typeof c && 0 < c ? d + c : d) : c = d;
        switch (a) {
          case 1:
            var e = -1;
            break;
          case 2:
            e = 250;
            break;
          case 5:
            e = 1073741823;
            break;
          case 4:
            e = 1e4;
            break;
          default:
            e = 5e3;
        }
        e = c + e;
        a = { id: u++, callback: b, priorityLevel: a, startTime: c, expirationTime: e, sortIndex: -1 };
        c > d ? (a.sortIndex = c, f(t, a), null === h(r2) && a === h(t) && (B ? (E(L), L = -1) : B = true, K(H, c - d))) : (a.sortIndex = e, f(r2, a), A || z || (A = true, I(J)));
        return a;
      };
      exports2.unstable_shouldYield = M;
      exports2.unstable_wrapCallback = function(a) {
        var b = y;
        return function() {
          var c = y;
          y = b;
          try {
            return a.apply(this, arguments);
          } finally {
            y = c;
          }
        };
      };
    })(scheduler_production_min);
    return scheduler_production_min;
  }
  var hasRequiredScheduler;
  function requireScheduler() {
    if (hasRequiredScheduler) return scheduler.exports;
    hasRequiredScheduler = 1;
    {
      scheduler.exports = requireScheduler_production_min();
    }
    return scheduler.exports;
  }
  /**
   * @license React
   * react-dom.production.min.js
   *
   * Copyright (c) Facebook, Inc. and its affiliates.
   *
   * This source code is licensed under the MIT license found in the
   * LICENSE file in the root directory of this source tree.
   */
  var hasRequiredReactDom_production_min;
  function requireReactDom_production_min() {
    if (hasRequiredReactDom_production_min) return reactDom_production_min;
    hasRequiredReactDom_production_min = 1;
    var aa = requireReact(), ca = requireScheduler();
    function p(a) {
      for (var b = "https://reactjs.org/docs/error-decoder.html?invariant=" + a, c = 1; c < arguments.length; c++) b += "&args[]=" + encodeURIComponent(arguments[c]);
      return "Minified React error #" + a + "; visit " + b + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
    }
    var da = /* @__PURE__ */ new Set(), ea = {};
    function fa(a, b) {
      ha(a, b);
      ha(a + "Capture", b);
    }
    function ha(a, b) {
      ea[a] = b;
      for (a = 0; a < b.length; a++) da.add(b[a]);
    }
    var ia = !("undefined" === typeof window || "undefined" === typeof window.document || "undefined" === typeof window.document.createElement), ja = Object.prototype.hasOwnProperty, ka = /^[:A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD][:A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD\-.0-9\u00B7\u0300-\u036F\u203F-\u2040]*$/, la = {}, ma = {};
    function oa(a) {
      if (ja.call(ma, a)) return true;
      if (ja.call(la, a)) return false;
      if (ka.test(a)) return ma[a] = true;
      la[a] = true;
      return false;
    }
    function pa(a, b, c, d) {
      if (null !== c && 0 === c.type) return false;
      switch (typeof b) {
        case "function":
        case "symbol":
          return true;
        case "boolean":
          if (d) return false;
          if (null !== c) return !c.acceptsBooleans;
          a = a.toLowerCase().slice(0, 5);
          return "data-" !== a && "aria-" !== a;
        default:
          return false;
      }
    }
    function qa(a, b, c, d) {
      if (null === b || "undefined" === typeof b || pa(a, b, c, d)) return true;
      if (d) return false;
      if (null !== c) switch (c.type) {
        case 3:
          return !b;
        case 4:
          return false === b;
        case 5:
          return isNaN(b);
        case 6:
          return isNaN(b) || 1 > b;
      }
      return false;
    }
    function v(a, b, c, d, e, f, g) {
      this.acceptsBooleans = 2 === b || 3 === b || 4 === b;
      this.attributeName = d;
      this.attributeNamespace = e;
      this.mustUseProperty = c;
      this.propertyName = a;
      this.type = b;
      this.sanitizeURL = f;
      this.removeEmptyString = g;
    }
    var z = {};
    "children dangerouslySetInnerHTML defaultValue defaultChecked innerHTML suppressContentEditableWarning suppressHydrationWarning style".split(" ").forEach(function(a) {
      z[a] = new v(a, 0, false, a, null, false, false);
    });
    [["acceptCharset", "accept-charset"], ["className", "class"], ["htmlFor", "for"], ["httpEquiv", "http-equiv"]].forEach(function(a) {
      var b = a[0];
      z[b] = new v(b, 1, false, a[1], null, false, false);
    });
    ["contentEditable", "draggable", "spellCheck", "value"].forEach(function(a) {
      z[a] = new v(a, 2, false, a.toLowerCase(), null, false, false);
    });
    ["autoReverse", "externalResourcesRequired", "focusable", "preserveAlpha"].forEach(function(a) {
      z[a] = new v(a, 2, false, a, null, false, false);
    });
    "allowFullScreen async autoFocus autoPlay controls default defer disabled disablePictureInPicture disableRemotePlayback formNoValidate hidden loop noModule noValidate open playsInline readOnly required reversed scoped seamless itemScope".split(" ").forEach(function(a) {
      z[a] = new v(a, 3, false, a.toLowerCase(), null, false, false);
    });
    ["checked", "multiple", "muted", "selected"].forEach(function(a) {
      z[a] = new v(a, 3, true, a, null, false, false);
    });
    ["capture", "download"].forEach(function(a) {
      z[a] = new v(a, 4, false, a, null, false, false);
    });
    ["cols", "rows", "size", "span"].forEach(function(a) {
      z[a] = new v(a, 6, false, a, null, false, false);
    });
    ["rowSpan", "start"].forEach(function(a) {
      z[a] = new v(a, 5, false, a.toLowerCase(), null, false, false);
    });
    var ra = /[\-:]([a-z])/g;
    function sa(a) {
      return a[1].toUpperCase();
    }
    "accent-height alignment-baseline arabic-form baseline-shift cap-height clip-path clip-rule color-interpolation color-interpolation-filters color-profile color-rendering dominant-baseline enable-background fill-opacity fill-rule flood-color flood-opacity font-family font-size font-size-adjust font-stretch font-style font-variant font-weight glyph-name glyph-orientation-horizontal glyph-orientation-vertical horiz-adv-x horiz-origin-x image-rendering letter-spacing lighting-color marker-end marker-mid marker-start overline-position overline-thickness paint-order panose-1 pointer-events rendering-intent shape-rendering stop-color stop-opacity strikethrough-position strikethrough-thickness stroke-dasharray stroke-dashoffset stroke-linecap stroke-linejoin stroke-miterlimit stroke-opacity stroke-width text-anchor text-decoration text-rendering underline-position underline-thickness unicode-bidi unicode-range units-per-em v-alphabetic v-hanging v-ideographic v-mathematical vector-effect vert-adv-y vert-origin-x vert-origin-y word-spacing writing-mode xmlns:xlink x-height".split(" ").forEach(function(a) {
      var b = a.replace(
        ra,
        sa
      );
      z[b] = new v(b, 1, false, a, null, false, false);
    });
    "xlink:actuate xlink:arcrole xlink:role xlink:show xlink:title xlink:type".split(" ").forEach(function(a) {
      var b = a.replace(ra, sa);
      z[b] = new v(b, 1, false, a, "http://www.w3.org/1999/xlink", false, false);
    });
    ["xml:base", "xml:lang", "xml:space"].forEach(function(a) {
      var b = a.replace(ra, sa);
      z[b] = new v(b, 1, false, a, "http://www.w3.org/XML/1998/namespace", false, false);
    });
    ["tabIndex", "crossOrigin"].forEach(function(a) {
      z[a] = new v(a, 1, false, a.toLowerCase(), null, false, false);
    });
    z.xlinkHref = new v("xlinkHref", 1, false, "xlink:href", "http://www.w3.org/1999/xlink", true, false);
    ["src", "href", "action", "formAction"].forEach(function(a) {
      z[a] = new v(a, 1, false, a.toLowerCase(), null, true, true);
    });
    function ta(a, b, c, d) {
      var e = z.hasOwnProperty(b) ? z[b] : null;
      if (null !== e ? 0 !== e.type : d || !(2 < b.length) || "o" !== b[0] && "O" !== b[0] || "n" !== b[1] && "N" !== b[1]) qa(b, c, e, d) && (c = null), d || null === e ? oa(b) && (null === c ? a.removeAttribute(b) : a.setAttribute(b, "" + c)) : e.mustUseProperty ? a[e.propertyName] = null === c ? 3 === e.type ? false : "" : c : (b = e.attributeName, d = e.attributeNamespace, null === c ? a.removeAttribute(b) : (e = e.type, c = 3 === e || 4 === e && true === c ? "" : "" + c, d ? a.setAttributeNS(d, b, c) : a.setAttribute(b, c)));
    }
    var ua = aa.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED, va = Symbol.for("react.element"), wa = Symbol.for("react.portal"), ya = Symbol.for("react.fragment"), za = Symbol.for("react.strict_mode"), Aa = Symbol.for("react.profiler"), Ba = Symbol.for("react.provider"), Ca = Symbol.for("react.context"), Da = Symbol.for("react.forward_ref"), Ea = Symbol.for("react.suspense"), Fa = Symbol.for("react.suspense_list"), Ga = Symbol.for("react.memo"), Ha = Symbol.for("react.lazy");
    var Ia = Symbol.for("react.offscreen");
    var Ja = Symbol.iterator;
    function Ka(a) {
      if (null === a || "object" !== typeof a) return null;
      a = Ja && a[Ja] || a["@@iterator"];
      return "function" === typeof a ? a : null;
    }
    var A = Object.assign, La;
    function Ma(a) {
      if (void 0 === La) try {
        throw Error();
      } catch (c) {
        var b = c.stack.trim().match(/\n( *(at )?)/);
        La = b && b[1] || "";
      }
      return "\n" + La + a;
    }
    var Na = false;
    function Oa(a, b) {
      if (!a || Na) return "";
      Na = true;
      var c = Error.prepareStackTrace;
      Error.prepareStackTrace = void 0;
      try {
        if (b) if (b = function() {
          throw Error();
        }, Object.defineProperty(b.prototype, "props", { set: function() {
          throw Error();
        } }), "object" === typeof Reflect && Reflect.construct) {
          try {
            Reflect.construct(b, []);
          } catch (l) {
            var d = l;
          }
          Reflect.construct(a, [], b);
        } else {
          try {
            b.call();
          } catch (l) {
            d = l;
          }
          a.call(b.prototype);
        }
        else {
          try {
            throw Error();
          } catch (l) {
            d = l;
          }
          a();
        }
      } catch (l) {
        if (l && d && "string" === typeof l.stack) {
          for (var e = l.stack.split("\n"), f = d.stack.split("\n"), g = e.length - 1, h = f.length - 1; 1 <= g && 0 <= h && e[g] !== f[h]; ) h--;
          for (; 1 <= g && 0 <= h; g--, h--) if (e[g] !== f[h]) {
            if (1 !== g || 1 !== h) {
              do
                if (g--, h--, 0 > h || e[g] !== f[h]) {
                  var k = "\n" + e[g].replace(" at new ", " at ");
                  a.displayName && k.includes("<anonymous>") && (k = k.replace("<anonymous>", a.displayName));
                  return k;
                }
              while (1 <= g && 0 <= h);
            }
            break;
          }
        }
      } finally {
        Na = false, Error.prepareStackTrace = c;
      }
      return (a = a ? a.displayName || a.name : "") ? Ma(a) : "";
    }
    function Pa(a) {
      switch (a.tag) {
        case 5:
          return Ma(a.type);
        case 16:
          return Ma("Lazy");
        case 13:
          return Ma("Suspense");
        case 19:
          return Ma("SuspenseList");
        case 0:
        case 2:
        case 15:
          return a = Oa(a.type, false), a;
        case 11:
          return a = Oa(a.type.render, false), a;
        case 1:
          return a = Oa(a.type, true), a;
        default:
          return "";
      }
    }
    function Qa(a) {
      if (null == a) return null;
      if ("function" === typeof a) return a.displayName || a.name || null;
      if ("string" === typeof a) return a;
      switch (a) {
        case ya:
          return "Fragment";
        case wa:
          return "Portal";
        case Aa:
          return "Profiler";
        case za:
          return "StrictMode";
        case Ea:
          return "Suspense";
        case Fa:
          return "SuspenseList";
      }
      if ("object" === typeof a) switch (a.$$typeof) {
        case Ca:
          return (a.displayName || "Context") + ".Consumer";
        case Ba:
          return (a._context.displayName || "Context") + ".Provider";
        case Da:
          var b = a.render;
          a = a.displayName;
          a || (a = b.displayName || b.name || "", a = "" !== a ? "ForwardRef(" + a + ")" : "ForwardRef");
          return a;
        case Ga:
          return b = a.displayName || null, null !== b ? b : Qa(a.type) || "Memo";
        case Ha:
          b = a._payload;
          a = a._init;
          try {
            return Qa(a(b));
          } catch (c) {
          }
      }
      return null;
    }
    function Ra(a) {
      var b = a.type;
      switch (a.tag) {
        case 24:
          return "Cache";
        case 9:
          return (b.displayName || "Context") + ".Consumer";
        case 10:
          return (b._context.displayName || "Context") + ".Provider";
        case 18:
          return "DehydratedFragment";
        case 11:
          return a = b.render, a = a.displayName || a.name || "", b.displayName || ("" !== a ? "ForwardRef(" + a + ")" : "ForwardRef");
        case 7:
          return "Fragment";
        case 5:
          return b;
        case 4:
          return "Portal";
        case 3:
          return "Root";
        case 6:
          return "Text";
        case 16:
          return Qa(b);
        case 8:
          return b === za ? "StrictMode" : "Mode";
        case 22:
          return "Offscreen";
        case 12:
          return "Profiler";
        case 21:
          return "Scope";
        case 13:
          return "Suspense";
        case 19:
          return "SuspenseList";
        case 25:
          return "TracingMarker";
        case 1:
        case 0:
        case 17:
        case 2:
        case 14:
        case 15:
          if ("function" === typeof b) return b.displayName || b.name || null;
          if ("string" === typeof b) return b;
      }
      return null;
    }
    function Sa(a) {
      switch (typeof a) {
        case "boolean":
        case "number":
        case "string":
        case "undefined":
          return a;
        case "object":
          return a;
        default:
          return "";
      }
    }
    function Ta(a) {
      var b = a.type;
      return (a = a.nodeName) && "input" === a.toLowerCase() && ("checkbox" === b || "radio" === b);
    }
    function Ua(a) {
      var b = Ta(a) ? "checked" : "value", c = Object.getOwnPropertyDescriptor(a.constructor.prototype, b), d = "" + a[b];
      if (!a.hasOwnProperty(b) && "undefined" !== typeof c && "function" === typeof c.get && "function" === typeof c.set) {
        var e = c.get, f = c.set;
        Object.defineProperty(a, b, { configurable: true, get: function() {
          return e.call(this);
        }, set: function(a2) {
          d = "" + a2;
          f.call(this, a2);
        } });
        Object.defineProperty(a, b, { enumerable: c.enumerable });
        return { getValue: function() {
          return d;
        }, setValue: function(a2) {
          d = "" + a2;
        }, stopTracking: function() {
          a._valueTracker = null;
          delete a[b];
        } };
      }
    }
    function Va(a) {
      a._valueTracker || (a._valueTracker = Ua(a));
    }
    function Wa(a) {
      if (!a) return false;
      var b = a._valueTracker;
      if (!b) return true;
      var c = b.getValue();
      var d = "";
      a && (d = Ta(a) ? a.checked ? "true" : "false" : a.value);
      a = d;
      return a !== c ? (b.setValue(a), true) : false;
    }
    function Xa(a) {
      a = a || ("undefined" !== typeof document ? document : void 0);
      if ("undefined" === typeof a) return null;
      try {
        return a.activeElement || a.body;
      } catch (b) {
        return a.body;
      }
    }
    function Ya(a, b) {
      var c = b.checked;
      return A({}, b, { defaultChecked: void 0, defaultValue: void 0, value: void 0, checked: null != c ? c : a._wrapperState.initialChecked });
    }
    function Za(a, b) {
      var c = null == b.defaultValue ? "" : b.defaultValue, d = null != b.checked ? b.checked : b.defaultChecked;
      c = Sa(null != b.value ? b.value : c);
      a._wrapperState = { initialChecked: d, initialValue: c, controlled: "checkbox" === b.type || "radio" === b.type ? null != b.checked : null != b.value };
    }
    function ab(a, b) {
      b = b.checked;
      null != b && ta(a, "checked", b, false);
    }
    function bb(a, b) {
      ab(a, b);
      var c = Sa(b.value), d = b.type;
      if (null != c) if ("number" === d) {
        if (0 === c && "" === a.value || a.value != c) a.value = "" + c;
      } else a.value !== "" + c && (a.value = "" + c);
      else if ("submit" === d || "reset" === d) {
        a.removeAttribute("value");
        return;
      }
      b.hasOwnProperty("value") ? cb(a, b.type, c) : b.hasOwnProperty("defaultValue") && cb(a, b.type, Sa(b.defaultValue));
      null == b.checked && null != b.defaultChecked && (a.defaultChecked = !!b.defaultChecked);
    }
    function db(a, b, c) {
      if (b.hasOwnProperty("value") || b.hasOwnProperty("defaultValue")) {
        var d = b.type;
        if (!("submit" !== d && "reset" !== d || void 0 !== b.value && null !== b.value)) return;
        b = "" + a._wrapperState.initialValue;
        c || b === a.value || (a.value = b);
        a.defaultValue = b;
      }
      c = a.name;
      "" !== c && (a.name = "");
      a.defaultChecked = !!a._wrapperState.initialChecked;
      "" !== c && (a.name = c);
    }
    function cb(a, b, c) {
      if ("number" !== b || Xa(a.ownerDocument) !== a) null == c ? a.defaultValue = "" + a._wrapperState.initialValue : a.defaultValue !== "" + c && (a.defaultValue = "" + c);
    }
    var eb = Array.isArray;
    function fb(a, b, c, d) {
      a = a.options;
      if (b) {
        b = {};
        for (var e = 0; e < c.length; e++) b["$" + c[e]] = true;
        for (c = 0; c < a.length; c++) e = b.hasOwnProperty("$" + a[c].value), a[c].selected !== e && (a[c].selected = e), e && d && (a[c].defaultSelected = true);
      } else {
        c = "" + Sa(c);
        b = null;
        for (e = 0; e < a.length; e++) {
          if (a[e].value === c) {
            a[e].selected = true;
            d && (a[e].defaultSelected = true);
            return;
          }
          null !== b || a[e].disabled || (b = a[e]);
        }
        null !== b && (b.selected = true);
      }
    }
    function gb(a, b) {
      if (null != b.dangerouslySetInnerHTML) throw Error(p(91));
      return A({}, b, { value: void 0, defaultValue: void 0, children: "" + a._wrapperState.initialValue });
    }
    function hb(a, b) {
      var c = b.value;
      if (null == c) {
        c = b.children;
        b = b.defaultValue;
        if (null != c) {
          if (null != b) throw Error(p(92));
          if (eb(c)) {
            if (1 < c.length) throw Error(p(93));
            c = c[0];
          }
          b = c;
        }
        null == b && (b = "");
        c = b;
      }
      a._wrapperState = { initialValue: Sa(c) };
    }
    function ib(a, b) {
      var c = Sa(b.value), d = Sa(b.defaultValue);
      null != c && (c = "" + c, c !== a.value && (a.value = c), null == b.defaultValue && a.defaultValue !== c && (a.defaultValue = c));
      null != d && (a.defaultValue = "" + d);
    }
    function jb(a) {
      var b = a.textContent;
      b === a._wrapperState.initialValue && "" !== b && null !== b && (a.value = b);
    }
    function kb(a) {
      switch (a) {
        case "svg":
          return "http://www.w3.org/2000/svg";
        case "math":
          return "http://www.w3.org/1998/Math/MathML";
        default:
          return "http://www.w3.org/1999/xhtml";
      }
    }
    function lb(a, b) {
      return null == a || "http://www.w3.org/1999/xhtml" === a ? kb(b) : "http://www.w3.org/2000/svg" === a && "foreignObject" === b ? "http://www.w3.org/1999/xhtml" : a;
    }
    var mb, nb = function(a) {
      return "undefined" !== typeof MSApp && MSApp.execUnsafeLocalFunction ? function(b, c, d, e) {
        MSApp.execUnsafeLocalFunction(function() {
          return a(b, c, d, e);
        });
      } : a;
    }(function(a, b) {
      if ("http://www.w3.org/2000/svg" !== a.namespaceURI || "innerHTML" in a) a.innerHTML = b;
      else {
        mb = mb || document.createElement("div");
        mb.innerHTML = "<svg>" + b.valueOf().toString() + "</svg>";
        for (b = mb.firstChild; a.firstChild; ) a.removeChild(a.firstChild);
        for (; b.firstChild; ) a.appendChild(b.firstChild);
      }
    });
    function ob(a, b) {
      if (b) {
        var c = a.firstChild;
        if (c && c === a.lastChild && 3 === c.nodeType) {
          c.nodeValue = b;
          return;
        }
      }
      a.textContent = b;
    }
    var pb = {
      animationIterationCount: true,
      aspectRatio: true,
      borderImageOutset: true,
      borderImageSlice: true,
      borderImageWidth: true,
      boxFlex: true,
      boxFlexGroup: true,
      boxOrdinalGroup: true,
      columnCount: true,
      columns: true,
      flex: true,
      flexGrow: true,
      flexPositive: true,
      flexShrink: true,
      flexNegative: true,
      flexOrder: true,
      gridArea: true,
      gridRow: true,
      gridRowEnd: true,
      gridRowSpan: true,
      gridRowStart: true,
      gridColumn: true,
      gridColumnEnd: true,
      gridColumnSpan: true,
      gridColumnStart: true,
      fontWeight: true,
      lineClamp: true,
      lineHeight: true,
      opacity: true,
      order: true,
      orphans: true,
      tabSize: true,
      widows: true,
      zIndex: true,
      zoom: true,
      fillOpacity: true,
      floodOpacity: true,
      stopOpacity: true,
      strokeDasharray: true,
      strokeDashoffset: true,
      strokeMiterlimit: true,
      strokeOpacity: true,
      strokeWidth: true
    }, qb = ["Webkit", "ms", "Moz", "O"];
    Object.keys(pb).forEach(function(a) {
      qb.forEach(function(b) {
        b = b + a.charAt(0).toUpperCase() + a.substring(1);
        pb[b] = pb[a];
      });
    });
    function rb(a, b, c) {
      return null == b || "boolean" === typeof b || "" === b ? "" : c || "number" !== typeof b || 0 === b || pb.hasOwnProperty(a) && pb[a] ? ("" + b).trim() : b + "px";
    }
    function sb(a, b) {
      a = a.style;
      for (var c in b) if (b.hasOwnProperty(c)) {
        var d = 0 === c.indexOf("--"), e = rb(c, b[c], d);
        "float" === c && (c = "cssFloat");
        d ? a.setProperty(c, e) : a[c] = e;
      }
    }
    var tb = A({ menuitem: true }, { area: true, base: true, br: true, col: true, embed: true, hr: true, img: true, input: true, keygen: true, link: true, meta: true, param: true, source: true, track: true, wbr: true });
    function ub(a, b) {
      if (b) {
        if (tb[a] && (null != b.children || null != b.dangerouslySetInnerHTML)) throw Error(p(137, a));
        if (null != b.dangerouslySetInnerHTML) {
          if (null != b.children) throw Error(p(60));
          if ("object" !== typeof b.dangerouslySetInnerHTML || !("__html" in b.dangerouslySetInnerHTML)) throw Error(p(61));
        }
        if (null != b.style && "object" !== typeof b.style) throw Error(p(62));
      }
    }
    function vb(a, b) {
      if (-1 === a.indexOf("-")) return "string" === typeof b.is;
      switch (a) {
        case "annotation-xml":
        case "color-profile":
        case "font-face":
        case "font-face-src":
        case "font-face-uri":
        case "font-face-format":
        case "font-face-name":
        case "missing-glyph":
          return false;
        default:
          return true;
      }
    }
    var wb = null;
    function xb(a) {
      a = a.target || a.srcElement || window;
      a.correspondingUseElement && (a = a.correspondingUseElement);
      return 3 === a.nodeType ? a.parentNode : a;
    }
    var yb = null, zb = null, Ab = null;
    function Bb(a) {
      if (a = Cb(a)) {
        if ("function" !== typeof yb) throw Error(p(280));
        var b = a.stateNode;
        b && (b = Db(b), yb(a.stateNode, a.type, b));
      }
    }
    function Eb(a) {
      zb ? Ab ? Ab.push(a) : Ab = [a] : zb = a;
    }
    function Fb() {
      if (zb) {
        var a = zb, b = Ab;
        Ab = zb = null;
        Bb(a);
        if (b) for (a = 0; a < b.length; a++) Bb(b[a]);
      }
    }
    function Gb(a, b) {
      return a(b);
    }
    function Hb() {
    }
    var Ib = false;
    function Jb(a, b, c) {
      if (Ib) return a(b, c);
      Ib = true;
      try {
        return Gb(a, b, c);
      } finally {
        if (Ib = false, null !== zb || null !== Ab) Hb(), Fb();
      }
    }
    function Kb(a, b) {
      var c = a.stateNode;
      if (null === c) return null;
      var d = Db(c);
      if (null === d) return null;
      c = d[b];
      a: switch (b) {
        case "onClick":
        case "onClickCapture":
        case "onDoubleClick":
        case "onDoubleClickCapture":
        case "onMouseDown":
        case "onMouseDownCapture":
        case "onMouseMove":
        case "onMouseMoveCapture":
        case "onMouseUp":
        case "onMouseUpCapture":
        case "onMouseEnter":
          (d = !d.disabled) || (a = a.type, d = !("button" === a || "input" === a || "select" === a || "textarea" === a));
          a = !d;
          break a;
        default:
          a = false;
      }
      if (a) return null;
      if (c && "function" !== typeof c) throw Error(p(231, b, typeof c));
      return c;
    }
    var Lb = false;
    if (ia) try {
      var Mb = {};
      Object.defineProperty(Mb, "passive", { get: function() {
        Lb = true;
      } });
      window.addEventListener("test", Mb, Mb);
      window.removeEventListener("test", Mb, Mb);
    } catch (a) {
      Lb = false;
    }
    function Nb(a, b, c, d, e, f, g, h, k) {
      var l = Array.prototype.slice.call(arguments, 3);
      try {
        b.apply(c, l);
      } catch (m) {
        this.onError(m);
      }
    }
    var Ob = false, Pb = null, Qb = false, Rb = null, Sb = { onError: function(a) {
      Ob = true;
      Pb = a;
    } };
    function Tb(a, b, c, d, e, f, g, h, k) {
      Ob = false;
      Pb = null;
      Nb.apply(Sb, arguments);
    }
    function Ub(a, b, c, d, e, f, g, h, k) {
      Tb.apply(this, arguments);
      if (Ob) {
        if (Ob) {
          var l = Pb;
          Ob = false;
          Pb = null;
        } else throw Error(p(198));
        Qb || (Qb = true, Rb = l);
      }
    }
    function Vb(a) {
      var b = a, c = a;
      if (a.alternate) for (; b.return; ) b = b.return;
      else {
        a = b;
        do
          b = a, 0 !== (b.flags & 4098) && (c = b.return), a = b.return;
        while (a);
      }
      return 3 === b.tag ? c : null;
    }
    function Wb(a) {
      if (13 === a.tag) {
        var b = a.memoizedState;
        null === b && (a = a.alternate, null !== a && (b = a.memoizedState));
        if (null !== b) return b.dehydrated;
      }
      return null;
    }
    function Xb(a) {
      if (Vb(a) !== a) throw Error(p(188));
    }
    function Yb(a) {
      var b = a.alternate;
      if (!b) {
        b = Vb(a);
        if (null === b) throw Error(p(188));
        return b !== a ? null : a;
      }
      for (var c = a, d = b; ; ) {
        var e = c.return;
        if (null === e) break;
        var f = e.alternate;
        if (null === f) {
          d = e.return;
          if (null !== d) {
            c = d;
            continue;
          }
          break;
        }
        if (e.child === f.child) {
          for (f = e.child; f; ) {
            if (f === c) return Xb(e), a;
            if (f === d) return Xb(e), b;
            f = f.sibling;
          }
          throw Error(p(188));
        }
        if (c.return !== d.return) c = e, d = f;
        else {
          for (var g = false, h = e.child; h; ) {
            if (h === c) {
              g = true;
              c = e;
              d = f;
              break;
            }
            if (h === d) {
              g = true;
              d = e;
              c = f;
              break;
            }
            h = h.sibling;
          }
          if (!g) {
            for (h = f.child; h; ) {
              if (h === c) {
                g = true;
                c = f;
                d = e;
                break;
              }
              if (h === d) {
                g = true;
                d = f;
                c = e;
                break;
              }
              h = h.sibling;
            }
            if (!g) throw Error(p(189));
          }
        }
        if (c.alternate !== d) throw Error(p(190));
      }
      if (3 !== c.tag) throw Error(p(188));
      return c.stateNode.current === c ? a : b;
    }
    function Zb(a) {
      a = Yb(a);
      return null !== a ? $b(a) : null;
    }
    function $b(a) {
      if (5 === a.tag || 6 === a.tag) return a;
      for (a = a.child; null !== a; ) {
        var b = $b(a);
        if (null !== b) return b;
        a = a.sibling;
      }
      return null;
    }
    var ac = ca.unstable_scheduleCallback, bc = ca.unstable_cancelCallback, cc = ca.unstable_shouldYield, dc = ca.unstable_requestPaint, B = ca.unstable_now, ec = ca.unstable_getCurrentPriorityLevel, fc = ca.unstable_ImmediatePriority, gc = ca.unstable_UserBlockingPriority, hc = ca.unstable_NormalPriority, ic = ca.unstable_LowPriority, jc = ca.unstable_IdlePriority, kc = null, lc = null;
    function mc(a) {
      if (lc && "function" === typeof lc.onCommitFiberRoot) try {
        lc.onCommitFiberRoot(kc, a, void 0, 128 === (a.current.flags & 128));
      } catch (b) {
      }
    }
    var oc = Math.clz32 ? Math.clz32 : nc, pc = Math.log, qc = Math.LN2;
    function nc(a) {
      a >>>= 0;
      return 0 === a ? 32 : 31 - (pc(a) / qc | 0) | 0;
    }
    var rc = 64, sc = 4194304;
    function tc(a) {
      switch (a & -a) {
        case 1:
          return 1;
        case 2:
          return 2;
        case 4:
          return 4;
        case 8:
          return 8;
        case 16:
          return 16;
        case 32:
          return 32;
        case 64:
        case 128:
        case 256:
        case 512:
        case 1024:
        case 2048:
        case 4096:
        case 8192:
        case 16384:
        case 32768:
        case 65536:
        case 131072:
        case 262144:
        case 524288:
        case 1048576:
        case 2097152:
          return a & 4194240;
        case 4194304:
        case 8388608:
        case 16777216:
        case 33554432:
        case 67108864:
          return a & 130023424;
        case 134217728:
          return 134217728;
        case 268435456:
          return 268435456;
        case 536870912:
          return 536870912;
        case 1073741824:
          return 1073741824;
        default:
          return a;
      }
    }
    function uc(a, b) {
      var c = a.pendingLanes;
      if (0 === c) return 0;
      var d = 0, e = a.suspendedLanes, f = a.pingedLanes, g = c & 268435455;
      if (0 !== g) {
        var h = g & ~e;
        0 !== h ? d = tc(h) : (f &= g, 0 !== f && (d = tc(f)));
      } else g = c & ~e, 0 !== g ? d = tc(g) : 0 !== f && (d = tc(f));
      if (0 === d) return 0;
      if (0 !== b && b !== d && 0 === (b & e) && (e = d & -d, f = b & -b, e >= f || 16 === e && 0 !== (f & 4194240))) return b;
      0 !== (d & 4) && (d |= c & 16);
      b = a.entangledLanes;
      if (0 !== b) for (a = a.entanglements, b &= d; 0 < b; ) c = 31 - oc(b), e = 1 << c, d |= a[c], b &= ~e;
      return d;
    }
    function vc(a, b) {
      switch (a) {
        case 1:
        case 2:
        case 4:
          return b + 250;
        case 8:
        case 16:
        case 32:
        case 64:
        case 128:
        case 256:
        case 512:
        case 1024:
        case 2048:
        case 4096:
        case 8192:
        case 16384:
        case 32768:
        case 65536:
        case 131072:
        case 262144:
        case 524288:
        case 1048576:
        case 2097152:
          return b + 5e3;
        case 4194304:
        case 8388608:
        case 16777216:
        case 33554432:
        case 67108864:
          return -1;
        case 134217728:
        case 268435456:
        case 536870912:
        case 1073741824:
          return -1;
        default:
          return -1;
      }
    }
    function wc(a, b) {
      for (var c = a.suspendedLanes, d = a.pingedLanes, e = a.expirationTimes, f = a.pendingLanes; 0 < f; ) {
        var g = 31 - oc(f), h = 1 << g, k = e[g];
        if (-1 === k) {
          if (0 === (h & c) || 0 !== (h & d)) e[g] = vc(h, b);
        } else k <= b && (a.expiredLanes |= h);
        f &= ~h;
      }
    }
    function xc(a) {
      a = a.pendingLanes & -1073741825;
      return 0 !== a ? a : a & 1073741824 ? 1073741824 : 0;
    }
    function yc() {
      var a = rc;
      rc <<= 1;
      0 === (rc & 4194240) && (rc = 64);
      return a;
    }
    function zc(a) {
      for (var b = [], c = 0; 31 > c; c++) b.push(a);
      return b;
    }
    function Ac(a, b, c) {
      a.pendingLanes |= b;
      536870912 !== b && (a.suspendedLanes = 0, a.pingedLanes = 0);
      a = a.eventTimes;
      b = 31 - oc(b);
      a[b] = c;
    }
    function Bc(a, b) {
      var c = a.pendingLanes & ~b;
      a.pendingLanes = b;
      a.suspendedLanes = 0;
      a.pingedLanes = 0;
      a.expiredLanes &= b;
      a.mutableReadLanes &= b;
      a.entangledLanes &= b;
      b = a.entanglements;
      var d = a.eventTimes;
      for (a = a.expirationTimes; 0 < c; ) {
        var e = 31 - oc(c), f = 1 << e;
        b[e] = 0;
        d[e] = -1;
        a[e] = -1;
        c &= ~f;
      }
    }
    function Cc(a, b) {
      var c = a.entangledLanes |= b;
      for (a = a.entanglements; c; ) {
        var d = 31 - oc(c), e = 1 << d;
        e & b | a[d] & b && (a[d] |= b);
        c &= ~e;
      }
    }
    var C = 0;
    function Dc(a) {
      a &= -a;
      return 1 < a ? 4 < a ? 0 !== (a & 268435455) ? 16 : 536870912 : 4 : 1;
    }
    var Ec, Fc, Gc, Hc, Ic, Jc = false, Kc = [], Lc = null, Mc = null, Nc = null, Oc = /* @__PURE__ */ new Map(), Pc = /* @__PURE__ */ new Map(), Qc = [], Rc = "mousedown mouseup touchcancel touchend touchstart auxclick dblclick pointercancel pointerdown pointerup dragend dragstart drop compositionend compositionstart keydown keypress keyup input textInput copy cut paste click change contextmenu reset submit".split(" ");
    function Sc(a, b) {
      switch (a) {
        case "focusin":
        case "focusout":
          Lc = null;
          break;
        case "dragenter":
        case "dragleave":
          Mc = null;
          break;
        case "mouseover":
        case "mouseout":
          Nc = null;
          break;
        case "pointerover":
        case "pointerout":
          Oc.delete(b.pointerId);
          break;
        case "gotpointercapture":
        case "lostpointercapture":
          Pc.delete(b.pointerId);
      }
    }
    function Tc(a, b, c, d, e, f) {
      if (null === a || a.nativeEvent !== f) return a = { blockedOn: b, domEventName: c, eventSystemFlags: d, nativeEvent: f, targetContainers: [e] }, null !== b && (b = Cb(b), null !== b && Fc(b)), a;
      a.eventSystemFlags |= d;
      b = a.targetContainers;
      null !== e && -1 === b.indexOf(e) && b.push(e);
      return a;
    }
    function Uc(a, b, c, d, e) {
      switch (b) {
        case "focusin":
          return Lc = Tc(Lc, a, b, c, d, e), true;
        case "dragenter":
          return Mc = Tc(Mc, a, b, c, d, e), true;
        case "mouseover":
          return Nc = Tc(Nc, a, b, c, d, e), true;
        case "pointerover":
          var f = e.pointerId;
          Oc.set(f, Tc(Oc.get(f) || null, a, b, c, d, e));
          return true;
        case "gotpointercapture":
          return f = e.pointerId, Pc.set(f, Tc(Pc.get(f) || null, a, b, c, d, e)), true;
      }
      return false;
    }
    function Vc(a) {
      var b = Wc(a.target);
      if (null !== b) {
        var c = Vb(b);
        if (null !== c) {
          if (b = c.tag, 13 === b) {
            if (b = Wb(c), null !== b) {
              a.blockedOn = b;
              Ic(a.priority, function() {
                Gc(c);
              });
              return;
            }
          } else if (3 === b && c.stateNode.current.memoizedState.isDehydrated) {
            a.blockedOn = 3 === c.tag ? c.stateNode.containerInfo : null;
            return;
          }
        }
      }
      a.blockedOn = null;
    }
    function Xc(a) {
      if (null !== a.blockedOn) return false;
      for (var b = a.targetContainers; 0 < b.length; ) {
        var c = Yc(a.domEventName, a.eventSystemFlags, b[0], a.nativeEvent);
        if (null === c) {
          c = a.nativeEvent;
          var d = new c.constructor(c.type, c);
          wb = d;
          c.target.dispatchEvent(d);
          wb = null;
        } else return b = Cb(c), null !== b && Fc(b), a.blockedOn = c, false;
        b.shift();
      }
      return true;
    }
    function Zc(a, b, c) {
      Xc(a) && c.delete(b);
    }
    function $c() {
      Jc = false;
      null !== Lc && Xc(Lc) && (Lc = null);
      null !== Mc && Xc(Mc) && (Mc = null);
      null !== Nc && Xc(Nc) && (Nc = null);
      Oc.forEach(Zc);
      Pc.forEach(Zc);
    }
    function ad(a, b) {
      a.blockedOn === b && (a.blockedOn = null, Jc || (Jc = true, ca.unstable_scheduleCallback(ca.unstable_NormalPriority, $c)));
    }
    function bd(a) {
      function b(b2) {
        return ad(b2, a);
      }
      if (0 < Kc.length) {
        ad(Kc[0], a);
        for (var c = 1; c < Kc.length; c++) {
          var d = Kc[c];
          d.blockedOn === a && (d.blockedOn = null);
        }
      }
      null !== Lc && ad(Lc, a);
      null !== Mc && ad(Mc, a);
      null !== Nc && ad(Nc, a);
      Oc.forEach(b);
      Pc.forEach(b);
      for (c = 0; c < Qc.length; c++) d = Qc[c], d.blockedOn === a && (d.blockedOn = null);
      for (; 0 < Qc.length && (c = Qc[0], null === c.blockedOn); ) Vc(c), null === c.blockedOn && Qc.shift();
    }
    var cd = ua.ReactCurrentBatchConfig, dd = true;
    function ed(a, b, c, d) {
      var e = C, f = cd.transition;
      cd.transition = null;
      try {
        C = 1, fd(a, b, c, d);
      } finally {
        C = e, cd.transition = f;
      }
    }
    function gd(a, b, c, d) {
      var e = C, f = cd.transition;
      cd.transition = null;
      try {
        C = 4, fd(a, b, c, d);
      } finally {
        C = e, cd.transition = f;
      }
    }
    function fd(a, b, c, d) {
      if (dd) {
        var e = Yc(a, b, c, d);
        if (null === e) hd(a, b, d, id, c), Sc(a, d);
        else if (Uc(e, a, b, c, d)) d.stopPropagation();
        else if (Sc(a, d), b & 4 && -1 < Rc.indexOf(a)) {
          for (; null !== e; ) {
            var f = Cb(e);
            null !== f && Ec(f);
            f = Yc(a, b, c, d);
            null === f && hd(a, b, d, id, c);
            if (f === e) break;
            e = f;
          }
          null !== e && d.stopPropagation();
        } else hd(a, b, d, null, c);
      }
    }
    var id = null;
    function Yc(a, b, c, d) {
      id = null;
      a = xb(d);
      a = Wc(a);
      if (null !== a) if (b = Vb(a), null === b) a = null;
      else if (c = b.tag, 13 === c) {
        a = Wb(b);
        if (null !== a) return a;
        a = null;
      } else if (3 === c) {
        if (b.stateNode.current.memoizedState.isDehydrated) return 3 === b.tag ? b.stateNode.containerInfo : null;
        a = null;
      } else b !== a && (a = null);
      id = a;
      return null;
    }
    function jd(a) {
      switch (a) {
        case "cancel":
        case "click":
        case "close":
        case "contextmenu":
        case "copy":
        case "cut":
        case "auxclick":
        case "dblclick":
        case "dragend":
        case "dragstart":
        case "drop":
        case "focusin":
        case "focusout":
        case "input":
        case "invalid":
        case "keydown":
        case "keypress":
        case "keyup":
        case "mousedown":
        case "mouseup":
        case "paste":
        case "pause":
        case "play":
        case "pointercancel":
        case "pointerdown":
        case "pointerup":
        case "ratechange":
        case "reset":
        case "resize":
        case "seeked":
        case "submit":
        case "touchcancel":
        case "touchend":
        case "touchstart":
        case "volumechange":
        case "change":
        case "selectionchange":
        case "textInput":
        case "compositionstart":
        case "compositionend":
        case "compositionupdate":
        case "beforeblur":
        case "afterblur":
        case "beforeinput":
        case "blur":
        case "fullscreenchange":
        case "focus":
        case "hashchange":
        case "popstate":
        case "select":
        case "selectstart":
          return 1;
        case "drag":
        case "dragenter":
        case "dragexit":
        case "dragleave":
        case "dragover":
        case "mousemove":
        case "mouseout":
        case "mouseover":
        case "pointermove":
        case "pointerout":
        case "pointerover":
        case "scroll":
        case "toggle":
        case "touchmove":
        case "wheel":
        case "mouseenter":
        case "mouseleave":
        case "pointerenter":
        case "pointerleave":
          return 4;
        case "message":
          switch (ec()) {
            case fc:
              return 1;
            case gc:
              return 4;
            case hc:
            case ic:
              return 16;
            case jc:
              return 536870912;
            default:
              return 16;
          }
        default:
          return 16;
      }
    }
    var kd = null, ld = null, md = null;
    function nd() {
      if (md) return md;
      var a, b = ld, c = b.length, d, e = "value" in kd ? kd.value : kd.textContent, f = e.length;
      for (a = 0; a < c && b[a] === e[a]; a++) ;
      var g = c - a;
      for (d = 1; d <= g && b[c - d] === e[f - d]; d++) ;
      return md = e.slice(a, 1 < d ? 1 - d : void 0);
    }
    function od(a) {
      var b = a.keyCode;
      "charCode" in a ? (a = a.charCode, 0 === a && 13 === b && (a = 13)) : a = b;
      10 === a && (a = 13);
      return 32 <= a || 13 === a ? a : 0;
    }
    function pd() {
      return true;
    }
    function qd() {
      return false;
    }
    function rd(a) {
      function b(b2, d, e, f, g) {
        this._reactName = b2;
        this._targetInst = e;
        this.type = d;
        this.nativeEvent = f;
        this.target = g;
        this.currentTarget = null;
        for (var c in a) a.hasOwnProperty(c) && (b2 = a[c], this[c] = b2 ? b2(f) : f[c]);
        this.isDefaultPrevented = (null != f.defaultPrevented ? f.defaultPrevented : false === f.returnValue) ? pd : qd;
        this.isPropagationStopped = qd;
        return this;
      }
      A(b.prototype, { preventDefault: function() {
        this.defaultPrevented = true;
        var a2 = this.nativeEvent;
        a2 && (a2.preventDefault ? a2.preventDefault() : "unknown" !== typeof a2.returnValue && (a2.returnValue = false), this.isDefaultPrevented = pd);
      }, stopPropagation: function() {
        var a2 = this.nativeEvent;
        a2 && (a2.stopPropagation ? a2.stopPropagation() : "unknown" !== typeof a2.cancelBubble && (a2.cancelBubble = true), this.isPropagationStopped = pd);
      }, persist: function() {
      }, isPersistent: pd });
      return b;
    }
    var sd = { eventPhase: 0, bubbles: 0, cancelable: 0, timeStamp: function(a) {
      return a.timeStamp || Date.now();
    }, defaultPrevented: 0, isTrusted: 0 }, td = rd(sd), ud = A({}, sd, { view: 0, detail: 0 }), vd = rd(ud), wd, xd, yd, Ad = A({}, ud, { screenX: 0, screenY: 0, clientX: 0, clientY: 0, pageX: 0, pageY: 0, ctrlKey: 0, shiftKey: 0, altKey: 0, metaKey: 0, getModifierState: zd, button: 0, buttons: 0, relatedTarget: function(a) {
      return void 0 === a.relatedTarget ? a.fromElement === a.srcElement ? a.toElement : a.fromElement : a.relatedTarget;
    }, movementX: function(a) {
      if ("movementX" in a) return a.movementX;
      a !== yd && (yd && "mousemove" === a.type ? (wd = a.screenX - yd.screenX, xd = a.screenY - yd.screenY) : xd = wd = 0, yd = a);
      return wd;
    }, movementY: function(a) {
      return "movementY" in a ? a.movementY : xd;
    } }), Bd = rd(Ad), Cd = A({}, Ad, { dataTransfer: 0 }), Dd = rd(Cd), Ed = A({}, ud, { relatedTarget: 0 }), Fd = rd(Ed), Gd = A({}, sd, { animationName: 0, elapsedTime: 0, pseudoElement: 0 }), Hd = rd(Gd), Id = A({}, sd, { clipboardData: function(a) {
      return "clipboardData" in a ? a.clipboardData : window.clipboardData;
    } }), Jd = rd(Id), Kd = A({}, sd, { data: 0 }), Ld = rd(Kd), Md = {
      Esc: "Escape",
      Spacebar: " ",
      Left: "ArrowLeft",
      Up: "ArrowUp",
      Right: "ArrowRight",
      Down: "ArrowDown",
      Del: "Delete",
      Win: "OS",
      Menu: "ContextMenu",
      Apps: "ContextMenu",
      Scroll: "ScrollLock",
      MozPrintableKey: "Unidentified"
    }, Nd = {
      8: "Backspace",
      9: "Tab",
      12: "Clear",
      13: "Enter",
      16: "Shift",
      17: "Control",
      18: "Alt",
      19: "Pause",
      20: "CapsLock",
      27: "Escape",
      32: " ",
      33: "PageUp",
      34: "PageDown",
      35: "End",
      36: "Home",
      37: "ArrowLeft",
      38: "ArrowUp",
      39: "ArrowRight",
      40: "ArrowDown",
      45: "Insert",
      46: "Delete",
      112: "F1",
      113: "F2",
      114: "F3",
      115: "F4",
      116: "F5",
      117: "F6",
      118: "F7",
      119: "F8",
      120: "F9",
      121: "F10",
      122: "F11",
      123: "F12",
      144: "NumLock",
      145: "ScrollLock",
      224: "Meta"
    }, Od = { Alt: "altKey", Control: "ctrlKey", Meta: "metaKey", Shift: "shiftKey" };
    function Pd(a) {
      var b = this.nativeEvent;
      return b.getModifierState ? b.getModifierState(a) : (a = Od[a]) ? !!b[a] : false;
    }
    function zd() {
      return Pd;
    }
    var Qd = A({}, ud, { key: function(a) {
      if (a.key) {
        var b = Md[a.key] || a.key;
        if ("Unidentified" !== b) return b;
      }
      return "keypress" === a.type ? (a = od(a), 13 === a ? "Enter" : String.fromCharCode(a)) : "keydown" === a.type || "keyup" === a.type ? Nd[a.keyCode] || "Unidentified" : "";
    }, code: 0, location: 0, ctrlKey: 0, shiftKey: 0, altKey: 0, metaKey: 0, repeat: 0, locale: 0, getModifierState: zd, charCode: function(a) {
      return "keypress" === a.type ? od(a) : 0;
    }, keyCode: function(a) {
      return "keydown" === a.type || "keyup" === a.type ? a.keyCode : 0;
    }, which: function(a) {
      return "keypress" === a.type ? od(a) : "keydown" === a.type || "keyup" === a.type ? a.keyCode : 0;
    } }), Rd = rd(Qd), Sd = A({}, Ad, { pointerId: 0, width: 0, height: 0, pressure: 0, tangentialPressure: 0, tiltX: 0, tiltY: 0, twist: 0, pointerType: 0, isPrimary: 0 }), Td = rd(Sd), Ud = A({}, ud, { touches: 0, targetTouches: 0, changedTouches: 0, altKey: 0, metaKey: 0, ctrlKey: 0, shiftKey: 0, getModifierState: zd }), Vd = rd(Ud), Wd = A({}, sd, { propertyName: 0, elapsedTime: 0, pseudoElement: 0 }), Xd = rd(Wd), Yd = A({}, Ad, {
      deltaX: function(a) {
        return "deltaX" in a ? a.deltaX : "wheelDeltaX" in a ? -a.wheelDeltaX : 0;
      },
      deltaY: function(a) {
        return "deltaY" in a ? a.deltaY : "wheelDeltaY" in a ? -a.wheelDeltaY : "wheelDelta" in a ? -a.wheelDelta : 0;
      },
      deltaZ: 0,
      deltaMode: 0
    }), Zd = rd(Yd), $d = [9, 13, 27, 32], ae = ia && "CompositionEvent" in window, be = null;
    ia && "documentMode" in document && (be = document.documentMode);
    var ce = ia && "TextEvent" in window && !be, de = ia && (!ae || be && 8 < be && 11 >= be), ee = String.fromCharCode(32), fe = false;
    function ge(a, b) {
      switch (a) {
        case "keyup":
          return -1 !== $d.indexOf(b.keyCode);
        case "keydown":
          return 229 !== b.keyCode;
        case "keypress":
        case "mousedown":
        case "focusout":
          return true;
        default:
          return false;
      }
    }
    function he(a) {
      a = a.detail;
      return "object" === typeof a && "data" in a ? a.data : null;
    }
    var ie = false;
    function je(a, b) {
      switch (a) {
        case "compositionend":
          return he(b);
        case "keypress":
          if (32 !== b.which) return null;
          fe = true;
          return ee;
        case "textInput":
          return a = b.data, a === ee && fe ? null : a;
        default:
          return null;
      }
    }
    function ke(a, b) {
      if (ie) return "compositionend" === a || !ae && ge(a, b) ? (a = nd(), md = ld = kd = null, ie = false, a) : null;
      switch (a) {
        case "paste":
          return null;
        case "keypress":
          if (!(b.ctrlKey || b.altKey || b.metaKey) || b.ctrlKey && b.altKey) {
            if (b.char && 1 < b.char.length) return b.char;
            if (b.which) return String.fromCharCode(b.which);
          }
          return null;
        case "compositionend":
          return de && "ko" !== b.locale ? null : b.data;
        default:
          return null;
      }
    }
    var le = { color: true, date: true, datetime: true, "datetime-local": true, email: true, month: true, number: true, password: true, range: true, search: true, tel: true, text: true, time: true, url: true, week: true };
    function me(a) {
      var b = a && a.nodeName && a.nodeName.toLowerCase();
      return "input" === b ? !!le[a.type] : "textarea" === b ? true : false;
    }
    function ne(a, b, c, d) {
      Eb(d);
      b = oe(b, "onChange");
      0 < b.length && (c = new td("onChange", "change", null, c, d), a.push({ event: c, listeners: b }));
    }
    var pe = null, qe = null;
    function re2(a) {
      se(a, 0);
    }
    function te(a) {
      var b = ue(a);
      if (Wa(b)) return a;
    }
    function ve(a, b) {
      if ("change" === a) return b;
    }
    var we = false;
    if (ia) {
      var xe;
      if (ia) {
        var ye = "oninput" in document;
        if (!ye) {
          var ze = document.createElement("div");
          ze.setAttribute("oninput", "return;");
          ye = "function" === typeof ze.oninput;
        }
        xe = ye;
      } else xe = false;
      we = xe && (!document.documentMode || 9 < document.documentMode);
    }
    function Ae() {
      pe && (pe.detachEvent("onpropertychange", Be), qe = pe = null);
    }
    function Be(a) {
      if ("value" === a.propertyName && te(qe)) {
        var b = [];
        ne(b, qe, a, xb(a));
        Jb(re2, b);
      }
    }
    function Ce(a, b, c) {
      "focusin" === a ? (Ae(), pe = b, qe = c, pe.attachEvent("onpropertychange", Be)) : "focusout" === a && Ae();
    }
    function De(a) {
      if ("selectionchange" === a || "keyup" === a || "keydown" === a) return te(qe);
    }
    function Ee(a, b) {
      if ("click" === a) return te(b);
    }
    function Fe(a, b) {
      if ("input" === a || "change" === a) return te(b);
    }
    function Ge(a, b) {
      return a === b && (0 !== a || 1 / a === 1 / b) || a !== a && b !== b;
    }
    var He = "function" === typeof Object.is ? Object.is : Ge;
    function Ie(a, b) {
      if (He(a, b)) return true;
      if ("object" !== typeof a || null === a || "object" !== typeof b || null === b) return false;
      var c = Object.keys(a), d = Object.keys(b);
      if (c.length !== d.length) return false;
      for (d = 0; d < c.length; d++) {
        var e = c[d];
        if (!ja.call(b, e) || !He(a[e], b[e])) return false;
      }
      return true;
    }
    function Je(a) {
      for (; a && a.firstChild; ) a = a.firstChild;
      return a;
    }
    function Ke(a, b) {
      var c = Je(a);
      a = 0;
      for (var d; c; ) {
        if (3 === c.nodeType) {
          d = a + c.textContent.length;
          if (a <= b && d >= b) return { node: c, offset: b - a };
          a = d;
        }
        a: {
          for (; c; ) {
            if (c.nextSibling) {
              c = c.nextSibling;
              break a;
            }
            c = c.parentNode;
          }
          c = void 0;
        }
        c = Je(c);
      }
    }
    function Le(a, b) {
      return a && b ? a === b ? true : a && 3 === a.nodeType ? false : b && 3 === b.nodeType ? Le(a, b.parentNode) : "contains" in a ? a.contains(b) : a.compareDocumentPosition ? !!(a.compareDocumentPosition(b) & 16) : false : false;
    }
    function Me() {
      for (var a = window, b = Xa(); b instanceof a.HTMLIFrameElement; ) {
        try {
          var c = "string" === typeof b.contentWindow.location.href;
        } catch (d) {
          c = false;
        }
        if (c) a = b.contentWindow;
        else break;
        b = Xa(a.document);
      }
      return b;
    }
    function Ne(a) {
      var b = a && a.nodeName && a.nodeName.toLowerCase();
      return b && ("input" === b && ("text" === a.type || "search" === a.type || "tel" === a.type || "url" === a.type || "password" === a.type) || "textarea" === b || "true" === a.contentEditable);
    }
    function Oe(a) {
      var b = Me(), c = a.focusedElem, d = a.selectionRange;
      if (b !== c && c && c.ownerDocument && Le(c.ownerDocument.documentElement, c)) {
        if (null !== d && Ne(c)) {
          if (b = d.start, a = d.end, void 0 === a && (a = b), "selectionStart" in c) c.selectionStart = b, c.selectionEnd = Math.min(a, c.value.length);
          else if (a = (b = c.ownerDocument || document) && b.defaultView || window, a.getSelection) {
            a = a.getSelection();
            var e = c.textContent.length, f = Math.min(d.start, e);
            d = void 0 === d.end ? f : Math.min(d.end, e);
            !a.extend && f > d && (e = d, d = f, f = e);
            e = Ke(c, f);
            var g = Ke(
              c,
              d
            );
            e && g && (1 !== a.rangeCount || a.anchorNode !== e.node || a.anchorOffset !== e.offset || a.focusNode !== g.node || a.focusOffset !== g.offset) && (b = b.createRange(), b.setStart(e.node, e.offset), a.removeAllRanges(), f > d ? (a.addRange(b), a.extend(g.node, g.offset)) : (b.setEnd(g.node, g.offset), a.addRange(b)));
          }
        }
        b = [];
        for (a = c; a = a.parentNode; ) 1 === a.nodeType && b.push({ element: a, left: a.scrollLeft, top: a.scrollTop });
        "function" === typeof c.focus && c.focus();
        for (c = 0; c < b.length; c++) a = b[c], a.element.scrollLeft = a.left, a.element.scrollTop = a.top;
      }
    }
    var Pe = ia && "documentMode" in document && 11 >= document.documentMode, Qe = null, Re = null, Se = null, Te = false;
    function Ue(a, b, c) {
      var d = c.window === c ? c.document : 9 === c.nodeType ? c : c.ownerDocument;
      Te || null == Qe || Qe !== Xa(d) || (d = Qe, "selectionStart" in d && Ne(d) ? d = { start: d.selectionStart, end: d.selectionEnd } : (d = (d.ownerDocument && d.ownerDocument.defaultView || window).getSelection(), d = { anchorNode: d.anchorNode, anchorOffset: d.anchorOffset, focusNode: d.focusNode, focusOffset: d.focusOffset }), Se && Ie(Se, d) || (Se = d, d = oe(Re, "onSelect"), 0 < d.length && (b = new td("onSelect", "select", null, b, c), a.push({ event: b, listeners: d }), b.target = Qe)));
    }
    function Ve(a, b) {
      var c = {};
      c[a.toLowerCase()] = b.toLowerCase();
      c["Webkit" + a] = "webkit" + b;
      c["Moz" + a] = "moz" + b;
      return c;
    }
    var We = { animationend: Ve("Animation", "AnimationEnd"), animationiteration: Ve("Animation", "AnimationIteration"), animationstart: Ve("Animation", "AnimationStart"), transitionend: Ve("Transition", "TransitionEnd") }, Xe = {}, Ye = {};
    ia && (Ye = document.createElement("div").style, "AnimationEvent" in window || (delete We.animationend.animation, delete We.animationiteration.animation, delete We.animationstart.animation), "TransitionEvent" in window || delete We.transitionend.transition);
    function Ze(a) {
      if (Xe[a]) return Xe[a];
      if (!We[a]) return a;
      var b = We[a], c;
      for (c in b) if (b.hasOwnProperty(c) && c in Ye) return Xe[a] = b[c];
      return a;
    }
    var $e = Ze("animationend"), af = Ze("animationiteration"), bf = Ze("animationstart"), cf = Ze("transitionend"), df = /* @__PURE__ */ new Map(), ef = "abort auxClick cancel canPlay canPlayThrough click close contextMenu copy cut drag dragEnd dragEnter dragExit dragLeave dragOver dragStart drop durationChange emptied encrypted ended error gotPointerCapture input invalid keyDown keyPress keyUp load loadedData loadedMetadata loadStart lostPointerCapture mouseDown mouseMove mouseOut mouseOver mouseUp paste pause play playing pointerCancel pointerDown pointerMove pointerOut pointerOver pointerUp progress rateChange reset resize seeked seeking stalled submit suspend timeUpdate touchCancel touchEnd touchStart volumeChange scroll toggle touchMove waiting wheel".split(" ");
    function ff(a, b) {
      df.set(a, b);
      fa(b, [a]);
    }
    for (var gf = 0; gf < ef.length; gf++) {
      var hf = ef[gf], jf = hf.toLowerCase(), kf = hf[0].toUpperCase() + hf.slice(1);
      ff(jf, "on" + kf);
    }
    ff($e, "onAnimationEnd");
    ff(af, "onAnimationIteration");
    ff(bf, "onAnimationStart");
    ff("dblclick", "onDoubleClick");
    ff("focusin", "onFocus");
    ff("focusout", "onBlur");
    ff(cf, "onTransitionEnd");
    ha("onMouseEnter", ["mouseout", "mouseover"]);
    ha("onMouseLeave", ["mouseout", "mouseover"]);
    ha("onPointerEnter", ["pointerout", "pointerover"]);
    ha("onPointerLeave", ["pointerout", "pointerover"]);
    fa("onChange", "change click focusin focusout input keydown keyup selectionchange".split(" "));
    fa("onSelect", "focusout contextmenu dragend focusin keydown keyup mousedown mouseup selectionchange".split(" "));
    fa("onBeforeInput", ["compositionend", "keypress", "textInput", "paste"]);
    fa("onCompositionEnd", "compositionend focusout keydown keypress keyup mousedown".split(" "));
    fa("onCompositionStart", "compositionstart focusout keydown keypress keyup mousedown".split(" "));
    fa("onCompositionUpdate", "compositionupdate focusout keydown keypress keyup mousedown".split(" "));
    var lf = "abort canplay canplaythrough durationchange emptied encrypted ended error loadeddata loadedmetadata loadstart pause play playing progress ratechange resize seeked seeking stalled suspend timeupdate volumechange waiting".split(" "), mf = new Set("cancel close invalid load scroll toggle".split(" ").concat(lf));
    function nf(a, b, c) {
      var d = a.type || "unknown-event";
      a.currentTarget = c;
      Ub(d, b, void 0, a);
      a.currentTarget = null;
    }
    function se(a, b) {
      b = 0 !== (b & 4);
      for (var c = 0; c < a.length; c++) {
        var d = a[c], e = d.event;
        d = d.listeners;
        a: {
          var f = void 0;
          if (b) for (var g = d.length - 1; 0 <= g; g--) {
            var h = d[g], k = h.instance, l = h.currentTarget;
            h = h.listener;
            if (k !== f && e.isPropagationStopped()) break a;
            nf(e, h, l);
            f = k;
          }
          else for (g = 0; g < d.length; g++) {
            h = d[g];
            k = h.instance;
            l = h.currentTarget;
            h = h.listener;
            if (k !== f && e.isPropagationStopped()) break a;
            nf(e, h, l);
            f = k;
          }
        }
      }
      if (Qb) throw a = Rb, Qb = false, Rb = null, a;
    }
    function D(a, b) {
      var c = b[of];
      void 0 === c && (c = b[of] = /* @__PURE__ */ new Set());
      var d = a + "__bubble";
      c.has(d) || (pf(b, a, 2, false), c.add(d));
    }
    function qf(a, b, c) {
      var d = 0;
      b && (d |= 4);
      pf(c, a, d, b);
    }
    var rf = "_reactListening" + Math.random().toString(36).slice(2);
    function sf(a) {
      if (!a[rf]) {
        a[rf] = true;
        da.forEach(function(b2) {
          "selectionchange" !== b2 && (mf.has(b2) || qf(b2, false, a), qf(b2, true, a));
        });
        var b = 9 === a.nodeType ? a : a.ownerDocument;
        null === b || b[rf] || (b[rf] = true, qf("selectionchange", false, b));
      }
    }
    function pf(a, b, c, d) {
      switch (jd(b)) {
        case 1:
          var e = ed;
          break;
        case 4:
          e = gd;
          break;
        default:
          e = fd;
      }
      c = e.bind(null, b, c, a);
      e = void 0;
      !Lb || "touchstart" !== b && "touchmove" !== b && "wheel" !== b || (e = true);
      d ? void 0 !== e ? a.addEventListener(b, c, { capture: true, passive: e }) : a.addEventListener(b, c, true) : void 0 !== e ? a.addEventListener(b, c, { passive: e }) : a.addEventListener(b, c, false);
    }
    function hd(a, b, c, d, e) {
      var f = d;
      if (0 === (b & 1) && 0 === (b & 2) && null !== d) a: for (; ; ) {
        if (null === d) return;
        var g = d.tag;
        if (3 === g || 4 === g) {
          var h = d.stateNode.containerInfo;
          if (h === e || 8 === h.nodeType && h.parentNode === e) break;
          if (4 === g) for (g = d.return; null !== g; ) {
            var k = g.tag;
            if (3 === k || 4 === k) {
              if (k = g.stateNode.containerInfo, k === e || 8 === k.nodeType && k.parentNode === e) return;
            }
            g = g.return;
          }
          for (; null !== h; ) {
            g = Wc(h);
            if (null === g) return;
            k = g.tag;
            if (5 === k || 6 === k) {
              d = f = g;
              continue a;
            }
            h = h.parentNode;
          }
        }
        d = d.return;
      }
      Jb(function() {
        var d2 = f, e2 = xb(c), g2 = [];
        a: {
          var h2 = df.get(a);
          if (void 0 !== h2) {
            var k2 = td, n = a;
            switch (a) {
              case "keypress":
                if (0 === od(c)) break a;
              case "keydown":
              case "keyup":
                k2 = Rd;
                break;
              case "focusin":
                n = "focus";
                k2 = Fd;
                break;
              case "focusout":
                n = "blur";
                k2 = Fd;
                break;
              case "beforeblur":
              case "afterblur":
                k2 = Fd;
                break;
              case "click":
                if (2 === c.button) break a;
              case "auxclick":
              case "dblclick":
              case "mousedown":
              case "mousemove":
              case "mouseup":
              case "mouseout":
              case "mouseover":
              case "contextmenu":
                k2 = Bd;
                break;
              case "drag":
              case "dragend":
              case "dragenter":
              case "dragexit":
              case "dragleave":
              case "dragover":
              case "dragstart":
              case "drop":
                k2 = Dd;
                break;
              case "touchcancel":
              case "touchend":
              case "touchmove":
              case "touchstart":
                k2 = Vd;
                break;
              case $e:
              case af:
              case bf:
                k2 = Hd;
                break;
              case cf:
                k2 = Xd;
                break;
              case "scroll":
                k2 = vd;
                break;
              case "wheel":
                k2 = Zd;
                break;
              case "copy":
              case "cut":
              case "paste":
                k2 = Jd;
                break;
              case "gotpointercapture":
              case "lostpointercapture":
              case "pointercancel":
              case "pointerdown":
              case "pointermove":
              case "pointerout":
              case "pointerover":
              case "pointerup":
                k2 = Td;
            }
            var t = 0 !== (b & 4), J = !t && "scroll" === a, x = t ? null !== h2 ? h2 + "Capture" : null : h2;
            t = [];
            for (var w = d2, u; null !== w; ) {
              u = w;
              var F = u.stateNode;
              5 === u.tag && null !== F && (u = F, null !== x && (F = Kb(w, x), null != F && t.push(tf(w, F, u))));
              if (J) break;
              w = w.return;
            }
            0 < t.length && (h2 = new k2(h2, n, null, c, e2), g2.push({ event: h2, listeners: t }));
          }
        }
        if (0 === (b & 7)) {
          a: {
            h2 = "mouseover" === a || "pointerover" === a;
            k2 = "mouseout" === a || "pointerout" === a;
            if (h2 && c !== wb && (n = c.relatedTarget || c.fromElement) && (Wc(n) || n[uf])) break a;
            if (k2 || h2) {
              h2 = e2.window === e2 ? e2 : (h2 = e2.ownerDocument) ? h2.defaultView || h2.parentWindow : window;
              if (k2) {
                if (n = c.relatedTarget || c.toElement, k2 = d2, n = n ? Wc(n) : null, null !== n && (J = Vb(n), n !== J || 5 !== n.tag && 6 !== n.tag)) n = null;
              } else k2 = null, n = d2;
              if (k2 !== n) {
                t = Bd;
                F = "onMouseLeave";
                x = "onMouseEnter";
                w = "mouse";
                if ("pointerout" === a || "pointerover" === a) t = Td, F = "onPointerLeave", x = "onPointerEnter", w = "pointer";
                J = null == k2 ? h2 : ue(k2);
                u = null == n ? h2 : ue(n);
                h2 = new t(F, w + "leave", k2, c, e2);
                h2.target = J;
                h2.relatedTarget = u;
                F = null;
                Wc(e2) === d2 && (t = new t(x, w + "enter", n, c, e2), t.target = u, t.relatedTarget = J, F = t);
                J = F;
                if (k2 && n) b: {
                  t = k2;
                  x = n;
                  w = 0;
                  for (u = t; u; u = vf(u)) w++;
                  u = 0;
                  for (F = x; F; F = vf(F)) u++;
                  for (; 0 < w - u; ) t = vf(t), w--;
                  for (; 0 < u - w; ) x = vf(x), u--;
                  for (; w--; ) {
                    if (t === x || null !== x && t === x.alternate) break b;
                    t = vf(t);
                    x = vf(x);
                  }
                  t = null;
                }
                else t = null;
                null !== k2 && wf(g2, h2, k2, t, false);
                null !== n && null !== J && wf(g2, J, n, t, true);
              }
            }
          }
          a: {
            h2 = d2 ? ue(d2) : window;
            k2 = h2.nodeName && h2.nodeName.toLowerCase();
            if ("select" === k2 || "input" === k2 && "file" === h2.type) var na = ve;
            else if (me(h2)) if (we) na = Fe;
            else {
              na = De;
              var xa = Ce;
            }
            else (k2 = h2.nodeName) && "input" === k2.toLowerCase() && ("checkbox" === h2.type || "radio" === h2.type) && (na = Ee);
            if (na && (na = na(a, d2))) {
              ne(g2, na, c, e2);
              break a;
            }
            xa && xa(a, h2, d2);
            "focusout" === a && (xa = h2._wrapperState) && xa.controlled && "number" === h2.type && cb(h2, "number", h2.value);
          }
          xa = d2 ? ue(d2) : window;
          switch (a) {
            case "focusin":
              if (me(xa) || "true" === xa.contentEditable) Qe = xa, Re = d2, Se = null;
              break;
            case "focusout":
              Se = Re = Qe = null;
              break;
            case "mousedown":
              Te = true;
              break;
            case "contextmenu":
            case "mouseup":
            case "dragend":
              Te = false;
              Ue(g2, c, e2);
              break;
            case "selectionchange":
              if (Pe) break;
            case "keydown":
            case "keyup":
              Ue(g2, c, e2);
          }
          var $a;
          if (ae) b: {
            switch (a) {
              case "compositionstart":
                var ba = "onCompositionStart";
                break b;
              case "compositionend":
                ba = "onCompositionEnd";
                break b;
              case "compositionupdate":
                ba = "onCompositionUpdate";
                break b;
            }
            ba = void 0;
          }
          else ie ? ge(a, c) && (ba = "onCompositionEnd") : "keydown" === a && 229 === c.keyCode && (ba = "onCompositionStart");
          ba && (de && "ko" !== c.locale && (ie || "onCompositionStart" !== ba ? "onCompositionEnd" === ba && ie && ($a = nd()) : (kd = e2, ld = "value" in kd ? kd.value : kd.textContent, ie = true)), xa = oe(d2, ba), 0 < xa.length && (ba = new Ld(ba, a, null, c, e2), g2.push({ event: ba, listeners: xa }), $a ? ba.data = $a : ($a = he(c), null !== $a && (ba.data = $a))));
          if ($a = ce ? je(a, c) : ke(a, c)) d2 = oe(d2, "onBeforeInput"), 0 < d2.length && (e2 = new Ld("onBeforeInput", "beforeinput", null, c, e2), g2.push({ event: e2, listeners: d2 }), e2.data = $a);
        }
        se(g2, b);
      });
    }
    function tf(a, b, c) {
      return { instance: a, listener: b, currentTarget: c };
    }
    function oe(a, b) {
      for (var c = b + "Capture", d = []; null !== a; ) {
        var e = a, f = e.stateNode;
        5 === e.tag && null !== f && (e = f, f = Kb(a, c), null != f && d.unshift(tf(a, f, e)), f = Kb(a, b), null != f && d.push(tf(a, f, e)));
        a = a.return;
      }
      return d;
    }
    function vf(a) {
      if (null === a) return null;
      do
        a = a.return;
      while (a && 5 !== a.tag);
      return a ? a : null;
    }
    function wf(a, b, c, d, e) {
      for (var f = b._reactName, g = []; null !== c && c !== d; ) {
        var h = c, k = h.alternate, l = h.stateNode;
        if (null !== k && k === d) break;
        5 === h.tag && null !== l && (h = l, e ? (k = Kb(c, f), null != k && g.unshift(tf(c, k, h))) : e || (k = Kb(c, f), null != k && g.push(tf(c, k, h))));
        c = c.return;
      }
      0 !== g.length && a.push({ event: b, listeners: g });
    }
    var xf = /\r\n?/g, yf = /\u0000|\uFFFD/g;
    function zf(a) {
      return ("string" === typeof a ? a : "" + a).replace(xf, "\n").replace(yf, "");
    }
    function Af(a, b, c) {
      b = zf(b);
      if (zf(a) !== b && c) throw Error(p(425));
    }
    function Bf() {
    }
    var Cf = null, Df = null;
    function Ef(a, b) {
      return "textarea" === a || "noscript" === a || "string" === typeof b.children || "number" === typeof b.children || "object" === typeof b.dangerouslySetInnerHTML && null !== b.dangerouslySetInnerHTML && null != b.dangerouslySetInnerHTML.__html;
    }
    var Ff = "function" === typeof setTimeout ? setTimeout : void 0, Gf = "function" === typeof clearTimeout ? clearTimeout : void 0, Hf = "function" === typeof Promise ? Promise : void 0, Jf = "function" === typeof queueMicrotask ? queueMicrotask : "undefined" !== typeof Hf ? function(a) {
      return Hf.resolve(null).then(a).catch(If);
    } : Ff;
    function If(a) {
      setTimeout(function() {
        throw a;
      });
    }
    function Kf(a, b) {
      var c = b, d = 0;
      do {
        var e = c.nextSibling;
        a.removeChild(c);
        if (e && 8 === e.nodeType) if (c = e.data, "/$" === c) {
          if (0 === d) {
            a.removeChild(e);
            bd(b);
            return;
          }
          d--;
        } else "$" !== c && "$?" !== c && "$!" !== c || d++;
        c = e;
      } while (c);
      bd(b);
    }
    function Lf(a) {
      for (; null != a; a = a.nextSibling) {
        var b = a.nodeType;
        if (1 === b || 3 === b) break;
        if (8 === b) {
          b = a.data;
          if ("$" === b || "$!" === b || "$?" === b) break;
          if ("/$" === b) return null;
        }
      }
      return a;
    }
    function Mf(a) {
      a = a.previousSibling;
      for (var b = 0; a; ) {
        if (8 === a.nodeType) {
          var c = a.data;
          if ("$" === c || "$!" === c || "$?" === c) {
            if (0 === b) return a;
            b--;
          } else "/$" === c && b++;
        }
        a = a.previousSibling;
      }
      return null;
    }
    var Nf = Math.random().toString(36).slice(2), Of = "__reactFiber$" + Nf, Pf = "__reactProps$" + Nf, uf = "__reactContainer$" + Nf, of = "__reactEvents$" + Nf, Qf = "__reactListeners$" + Nf, Rf = "__reactHandles$" + Nf;
    function Wc(a) {
      var b = a[Of];
      if (b) return b;
      for (var c = a.parentNode; c; ) {
        if (b = c[uf] || c[Of]) {
          c = b.alternate;
          if (null !== b.child || null !== c && null !== c.child) for (a = Mf(a); null !== a; ) {
            if (c = a[Of]) return c;
            a = Mf(a);
          }
          return b;
        }
        a = c;
        c = a.parentNode;
      }
      return null;
    }
    function Cb(a) {
      a = a[Of] || a[uf];
      return !a || 5 !== a.tag && 6 !== a.tag && 13 !== a.tag && 3 !== a.tag ? null : a;
    }
    function ue(a) {
      if (5 === a.tag || 6 === a.tag) return a.stateNode;
      throw Error(p(33));
    }
    function Db(a) {
      return a[Pf] || null;
    }
    var Sf = [], Tf = -1;
    function Uf(a) {
      return { current: a };
    }
    function E(a) {
      0 > Tf || (a.current = Sf[Tf], Sf[Tf] = null, Tf--);
    }
    function G(a, b) {
      Tf++;
      Sf[Tf] = a.current;
      a.current = b;
    }
    var Vf = {}, H = Uf(Vf), Wf = Uf(false), Xf = Vf;
    function Yf(a, b) {
      var c = a.type.contextTypes;
      if (!c) return Vf;
      var d = a.stateNode;
      if (d && d.__reactInternalMemoizedUnmaskedChildContext === b) return d.__reactInternalMemoizedMaskedChildContext;
      var e = {}, f;
      for (f in c) e[f] = b[f];
      d && (a = a.stateNode, a.__reactInternalMemoizedUnmaskedChildContext = b, a.__reactInternalMemoizedMaskedChildContext = e);
      return e;
    }
    function Zf(a) {
      a = a.childContextTypes;
      return null !== a && void 0 !== a;
    }
    function $f() {
      E(Wf);
      E(H);
    }
    function ag(a, b, c) {
      if (H.current !== Vf) throw Error(p(168));
      G(H, b);
      G(Wf, c);
    }
    function bg(a, b, c) {
      var d = a.stateNode;
      b = b.childContextTypes;
      if ("function" !== typeof d.getChildContext) return c;
      d = d.getChildContext();
      for (var e in d) if (!(e in b)) throw Error(p(108, Ra(a) || "Unknown", e));
      return A({}, c, d);
    }
    function cg(a) {
      a = (a = a.stateNode) && a.__reactInternalMemoizedMergedChildContext || Vf;
      Xf = H.current;
      G(H, a);
      G(Wf, Wf.current);
      return true;
    }
    function dg(a, b, c) {
      var d = a.stateNode;
      if (!d) throw Error(p(169));
      c ? (a = bg(a, b, Xf), d.__reactInternalMemoizedMergedChildContext = a, E(Wf), E(H), G(H, a)) : E(Wf);
      G(Wf, c);
    }
    var eg = null, fg = false, gg = false;
    function hg(a) {
      null === eg ? eg = [a] : eg.push(a);
    }
    function ig(a) {
      fg = true;
      hg(a);
    }
    function jg() {
      if (!gg && null !== eg) {
        gg = true;
        var a = 0, b = C;
        try {
          var c = eg;
          for (C = 1; a < c.length; a++) {
            var d = c[a];
            do
              d = d(true);
            while (null !== d);
          }
          eg = null;
          fg = false;
        } catch (e) {
          throw null !== eg && (eg = eg.slice(a + 1)), ac(fc, jg), e;
        } finally {
          C = b, gg = false;
        }
      }
      return null;
    }
    var kg = [], lg = 0, mg = null, ng = 0, og = [], pg = 0, qg = null, rg = 1, sg = "";
    function tg(a, b) {
      kg[lg++] = ng;
      kg[lg++] = mg;
      mg = a;
      ng = b;
    }
    function ug(a, b, c) {
      og[pg++] = rg;
      og[pg++] = sg;
      og[pg++] = qg;
      qg = a;
      var d = rg;
      a = sg;
      var e = 32 - oc(d) - 1;
      d &= ~(1 << e);
      c += 1;
      var f = 32 - oc(b) + e;
      if (30 < f) {
        var g = e - e % 5;
        f = (d & (1 << g) - 1).toString(32);
        d >>= g;
        e -= g;
        rg = 1 << 32 - oc(b) + e | c << e | d;
        sg = f + a;
      } else rg = 1 << f | c << e | d, sg = a;
    }
    function vg(a) {
      null !== a.return && (tg(a, 1), ug(a, 1, 0));
    }
    function wg(a) {
      for (; a === mg; ) mg = kg[--lg], kg[lg] = null, ng = kg[--lg], kg[lg] = null;
      for (; a === qg; ) qg = og[--pg], og[pg] = null, sg = og[--pg], og[pg] = null, rg = og[--pg], og[pg] = null;
    }
    var xg = null, yg = null, I = false, zg = null;
    function Ag(a, b) {
      var c = Bg(5, null, null, 0);
      c.elementType = "DELETED";
      c.stateNode = b;
      c.return = a;
      b = a.deletions;
      null === b ? (a.deletions = [c], a.flags |= 16) : b.push(c);
    }
    function Cg(a, b) {
      switch (a.tag) {
        case 5:
          var c = a.type;
          b = 1 !== b.nodeType || c.toLowerCase() !== b.nodeName.toLowerCase() ? null : b;
          return null !== b ? (a.stateNode = b, xg = a, yg = Lf(b.firstChild), true) : false;
        case 6:
          return b = "" === a.pendingProps || 3 !== b.nodeType ? null : b, null !== b ? (a.stateNode = b, xg = a, yg = null, true) : false;
        case 13:
          return b = 8 !== b.nodeType ? null : b, null !== b ? (c = null !== qg ? { id: rg, overflow: sg } : null, a.memoizedState = { dehydrated: b, treeContext: c, retryLane: 1073741824 }, c = Bg(18, null, null, 0), c.stateNode = b, c.return = a, a.child = c, xg = a, yg = null, true) : false;
        default:
          return false;
      }
    }
    function Dg(a) {
      return 0 !== (a.mode & 1) && 0 === (a.flags & 128);
    }
    function Eg(a) {
      if (I) {
        var b = yg;
        if (b) {
          var c = b;
          if (!Cg(a, b)) {
            if (Dg(a)) throw Error(p(418));
            b = Lf(c.nextSibling);
            var d = xg;
            b && Cg(a, b) ? Ag(d, c) : (a.flags = a.flags & -4097 | 2, I = false, xg = a);
          }
        } else {
          if (Dg(a)) throw Error(p(418));
          a.flags = a.flags & -4097 | 2;
          I = false;
          xg = a;
        }
      }
    }
    function Fg(a) {
      for (a = a.return; null !== a && 5 !== a.tag && 3 !== a.tag && 13 !== a.tag; ) a = a.return;
      xg = a;
    }
    function Gg(a) {
      if (a !== xg) return false;
      if (!I) return Fg(a), I = true, false;
      var b;
      (b = 3 !== a.tag) && !(b = 5 !== a.tag) && (b = a.type, b = "head" !== b && "body" !== b && !Ef(a.type, a.memoizedProps));
      if (b && (b = yg)) {
        if (Dg(a)) throw Hg(), Error(p(418));
        for (; b; ) Ag(a, b), b = Lf(b.nextSibling);
      }
      Fg(a);
      if (13 === a.tag) {
        a = a.memoizedState;
        a = null !== a ? a.dehydrated : null;
        if (!a) throw Error(p(317));
        a: {
          a = a.nextSibling;
          for (b = 0; a; ) {
            if (8 === a.nodeType) {
              var c = a.data;
              if ("/$" === c) {
                if (0 === b) {
                  yg = Lf(a.nextSibling);
                  break a;
                }
                b--;
              } else "$" !== c && "$!" !== c && "$?" !== c || b++;
            }
            a = a.nextSibling;
          }
          yg = null;
        }
      } else yg = xg ? Lf(a.stateNode.nextSibling) : null;
      return true;
    }
    function Hg() {
      for (var a = yg; a; ) a = Lf(a.nextSibling);
    }
    function Ig() {
      yg = xg = null;
      I = false;
    }
    function Jg(a) {
      null === zg ? zg = [a] : zg.push(a);
    }
    var Kg = ua.ReactCurrentBatchConfig;
    function Lg(a, b, c) {
      a = c.ref;
      if (null !== a && "function" !== typeof a && "object" !== typeof a) {
        if (c._owner) {
          c = c._owner;
          if (c) {
            if (1 !== c.tag) throw Error(p(309));
            var d = c.stateNode;
          }
          if (!d) throw Error(p(147, a));
          var e = d, f = "" + a;
          if (null !== b && null !== b.ref && "function" === typeof b.ref && b.ref._stringRef === f) return b.ref;
          b = function(a2) {
            var b2 = e.refs;
            null === a2 ? delete b2[f] : b2[f] = a2;
          };
          b._stringRef = f;
          return b;
        }
        if ("string" !== typeof a) throw Error(p(284));
        if (!c._owner) throw Error(p(290, a));
      }
      return a;
    }
    function Mg(a, b) {
      a = Object.prototype.toString.call(b);
      throw Error(p(31, "[object Object]" === a ? "object with keys {" + Object.keys(b).join(", ") + "}" : a));
    }
    function Ng(a) {
      var b = a._init;
      return b(a._payload);
    }
    function Og(a) {
      function b(b2, c2) {
        if (a) {
          var d2 = b2.deletions;
          null === d2 ? (b2.deletions = [c2], b2.flags |= 16) : d2.push(c2);
        }
      }
      function c(c2, d2) {
        if (!a) return null;
        for (; null !== d2; ) b(c2, d2), d2 = d2.sibling;
        return null;
      }
      function d(a2, b2) {
        for (a2 = /* @__PURE__ */ new Map(); null !== b2; ) null !== b2.key ? a2.set(b2.key, b2) : a2.set(b2.index, b2), b2 = b2.sibling;
        return a2;
      }
      function e(a2, b2) {
        a2 = Pg(a2, b2);
        a2.index = 0;
        a2.sibling = null;
        return a2;
      }
      function f(b2, c2, d2) {
        b2.index = d2;
        if (!a) return b2.flags |= 1048576, c2;
        d2 = b2.alternate;
        if (null !== d2) return d2 = d2.index, d2 < c2 ? (b2.flags |= 2, c2) : d2;
        b2.flags |= 2;
        return c2;
      }
      function g(b2) {
        a && null === b2.alternate && (b2.flags |= 2);
        return b2;
      }
      function h(a2, b2, c2, d2) {
        if (null === b2 || 6 !== b2.tag) return b2 = Qg(c2, a2.mode, d2), b2.return = a2, b2;
        b2 = e(b2, c2);
        b2.return = a2;
        return b2;
      }
      function k(a2, b2, c2, d2) {
        var f2 = c2.type;
        if (f2 === ya) return m(a2, b2, c2.props.children, d2, c2.key);
        if (null !== b2 && (b2.elementType === f2 || "object" === typeof f2 && null !== f2 && f2.$$typeof === Ha && Ng(f2) === b2.type)) return d2 = e(b2, c2.props), d2.ref = Lg(a2, b2, c2), d2.return = a2, d2;
        d2 = Rg(c2.type, c2.key, c2.props, null, a2.mode, d2);
        d2.ref = Lg(a2, b2, c2);
        d2.return = a2;
        return d2;
      }
      function l(a2, b2, c2, d2) {
        if (null === b2 || 4 !== b2.tag || b2.stateNode.containerInfo !== c2.containerInfo || b2.stateNode.implementation !== c2.implementation) return b2 = Sg(c2, a2.mode, d2), b2.return = a2, b2;
        b2 = e(b2, c2.children || []);
        b2.return = a2;
        return b2;
      }
      function m(a2, b2, c2, d2, f2) {
        if (null === b2 || 7 !== b2.tag) return b2 = Tg(c2, a2.mode, d2, f2), b2.return = a2, b2;
        b2 = e(b2, c2);
        b2.return = a2;
        return b2;
      }
      function q(a2, b2, c2) {
        if ("string" === typeof b2 && "" !== b2 || "number" === typeof b2) return b2 = Qg("" + b2, a2.mode, c2), b2.return = a2, b2;
        if ("object" === typeof b2 && null !== b2) {
          switch (b2.$$typeof) {
            case va:
              return c2 = Rg(b2.type, b2.key, b2.props, null, a2.mode, c2), c2.ref = Lg(a2, null, b2), c2.return = a2, c2;
            case wa:
              return b2 = Sg(b2, a2.mode, c2), b2.return = a2, b2;
            case Ha:
              var d2 = b2._init;
              return q(a2, d2(b2._payload), c2);
          }
          if (eb(b2) || Ka(b2)) return b2 = Tg(b2, a2.mode, c2, null), b2.return = a2, b2;
          Mg(a2, b2);
        }
        return null;
      }
      function r2(a2, b2, c2, d2) {
        var e2 = null !== b2 ? b2.key : null;
        if ("string" === typeof c2 && "" !== c2 || "number" === typeof c2) return null !== e2 ? null : h(a2, b2, "" + c2, d2);
        if ("object" === typeof c2 && null !== c2) {
          switch (c2.$$typeof) {
            case va:
              return c2.key === e2 ? k(a2, b2, c2, d2) : null;
            case wa:
              return c2.key === e2 ? l(a2, b2, c2, d2) : null;
            case Ha:
              return e2 = c2._init, r2(
                a2,
                b2,
                e2(c2._payload),
                d2
              );
          }
          if (eb(c2) || Ka(c2)) return null !== e2 ? null : m(a2, b2, c2, d2, null);
          Mg(a2, c2);
        }
        return null;
      }
      function y(a2, b2, c2, d2, e2) {
        if ("string" === typeof d2 && "" !== d2 || "number" === typeof d2) return a2 = a2.get(c2) || null, h(b2, a2, "" + d2, e2);
        if ("object" === typeof d2 && null !== d2) {
          switch (d2.$$typeof) {
            case va:
              return a2 = a2.get(null === d2.key ? c2 : d2.key) || null, k(b2, a2, d2, e2);
            case wa:
              return a2 = a2.get(null === d2.key ? c2 : d2.key) || null, l(b2, a2, d2, e2);
            case Ha:
              var f2 = d2._init;
              return y(a2, b2, c2, f2(d2._payload), e2);
          }
          if (eb(d2) || Ka(d2)) return a2 = a2.get(c2) || null, m(b2, a2, d2, e2, null);
          Mg(b2, d2);
        }
        return null;
      }
      function n(e2, g2, h2, k2) {
        for (var l2 = null, m2 = null, u = g2, w = g2 = 0, x = null; null !== u && w < h2.length; w++) {
          u.index > w ? (x = u, u = null) : x = u.sibling;
          var n2 = r2(e2, u, h2[w], k2);
          if (null === n2) {
            null === u && (u = x);
            break;
          }
          a && u && null === n2.alternate && b(e2, u);
          g2 = f(n2, g2, w);
          null === m2 ? l2 = n2 : m2.sibling = n2;
          m2 = n2;
          u = x;
        }
        if (w === h2.length) return c(e2, u), I && tg(e2, w), l2;
        if (null === u) {
          for (; w < h2.length; w++) u = q(e2, h2[w], k2), null !== u && (g2 = f(u, g2, w), null === m2 ? l2 = u : m2.sibling = u, m2 = u);
          I && tg(e2, w);
          return l2;
        }
        for (u = d(e2, u); w < h2.length; w++) x = y(u, e2, w, h2[w], k2), null !== x && (a && null !== x.alternate && u.delete(null === x.key ? w : x.key), g2 = f(x, g2, w), null === m2 ? l2 = x : m2.sibling = x, m2 = x);
        a && u.forEach(function(a2) {
          return b(e2, a2);
        });
        I && tg(e2, w);
        return l2;
      }
      function t(e2, g2, h2, k2) {
        var l2 = Ka(h2);
        if ("function" !== typeof l2) throw Error(p(150));
        h2 = l2.call(h2);
        if (null == h2) throw Error(p(151));
        for (var u = l2 = null, m2 = g2, w = g2 = 0, x = null, n2 = h2.next(); null !== m2 && !n2.done; w++, n2 = h2.next()) {
          m2.index > w ? (x = m2, m2 = null) : x = m2.sibling;
          var t2 = r2(e2, m2, n2.value, k2);
          if (null === t2) {
            null === m2 && (m2 = x);
            break;
          }
          a && m2 && null === t2.alternate && b(e2, m2);
          g2 = f(t2, g2, w);
          null === u ? l2 = t2 : u.sibling = t2;
          u = t2;
          m2 = x;
        }
        if (n2.done) return c(
          e2,
          m2
        ), I && tg(e2, w), l2;
        if (null === m2) {
          for (; !n2.done; w++, n2 = h2.next()) n2 = q(e2, n2.value, k2), null !== n2 && (g2 = f(n2, g2, w), null === u ? l2 = n2 : u.sibling = n2, u = n2);
          I && tg(e2, w);
          return l2;
        }
        for (m2 = d(e2, m2); !n2.done; w++, n2 = h2.next()) n2 = y(m2, e2, w, n2.value, k2), null !== n2 && (a && null !== n2.alternate && m2.delete(null === n2.key ? w : n2.key), g2 = f(n2, g2, w), null === u ? l2 = n2 : u.sibling = n2, u = n2);
        a && m2.forEach(function(a2) {
          return b(e2, a2);
        });
        I && tg(e2, w);
        return l2;
      }
      function J(a2, d2, f2, h2) {
        "object" === typeof f2 && null !== f2 && f2.type === ya && null === f2.key && (f2 = f2.props.children);
        if ("object" === typeof f2 && null !== f2) {
          switch (f2.$$typeof) {
            case va:
              a: {
                for (var k2 = f2.key, l2 = d2; null !== l2; ) {
                  if (l2.key === k2) {
                    k2 = f2.type;
                    if (k2 === ya) {
                      if (7 === l2.tag) {
                        c(a2, l2.sibling);
                        d2 = e(l2, f2.props.children);
                        d2.return = a2;
                        a2 = d2;
                        break a;
                      }
                    } else if (l2.elementType === k2 || "object" === typeof k2 && null !== k2 && k2.$$typeof === Ha && Ng(k2) === l2.type) {
                      c(a2, l2.sibling);
                      d2 = e(l2, f2.props);
                      d2.ref = Lg(a2, l2, f2);
                      d2.return = a2;
                      a2 = d2;
                      break a;
                    }
                    c(a2, l2);
                    break;
                  } else b(a2, l2);
                  l2 = l2.sibling;
                }
                f2.type === ya ? (d2 = Tg(f2.props.children, a2.mode, h2, f2.key), d2.return = a2, a2 = d2) : (h2 = Rg(f2.type, f2.key, f2.props, null, a2.mode, h2), h2.ref = Lg(a2, d2, f2), h2.return = a2, a2 = h2);
              }
              return g(a2);
            case wa:
              a: {
                for (l2 = f2.key; null !== d2; ) {
                  if (d2.key === l2) if (4 === d2.tag && d2.stateNode.containerInfo === f2.containerInfo && d2.stateNode.implementation === f2.implementation) {
                    c(a2, d2.sibling);
                    d2 = e(d2, f2.children || []);
                    d2.return = a2;
                    a2 = d2;
                    break a;
                  } else {
                    c(a2, d2);
                    break;
                  }
                  else b(a2, d2);
                  d2 = d2.sibling;
                }
                d2 = Sg(f2, a2.mode, h2);
                d2.return = a2;
                a2 = d2;
              }
              return g(a2);
            case Ha:
              return l2 = f2._init, J(a2, d2, l2(f2._payload), h2);
          }
          if (eb(f2)) return n(a2, d2, f2, h2);
          if (Ka(f2)) return t(a2, d2, f2, h2);
          Mg(a2, f2);
        }
        return "string" === typeof f2 && "" !== f2 || "number" === typeof f2 ? (f2 = "" + f2, null !== d2 && 6 === d2.tag ? (c(a2, d2.sibling), d2 = e(d2, f2), d2.return = a2, a2 = d2) : (c(a2, d2), d2 = Qg(f2, a2.mode, h2), d2.return = a2, a2 = d2), g(a2)) : c(a2, d2);
      }
      return J;
    }
    var Ug = Og(true), Vg = Og(false), Wg = Uf(null), Xg = null, Yg = null, Zg = null;
    function $g() {
      Zg = Yg = Xg = null;
    }
    function ah(a) {
      var b = Wg.current;
      E(Wg);
      a._currentValue = b;
    }
    function bh(a, b, c) {
      for (; null !== a; ) {
        var d = a.alternate;
        (a.childLanes & b) !== b ? (a.childLanes |= b, null !== d && (d.childLanes |= b)) : null !== d && (d.childLanes & b) !== b && (d.childLanes |= b);
        if (a === c) break;
        a = a.return;
      }
    }
    function ch(a, b) {
      Xg = a;
      Zg = Yg = null;
      a = a.dependencies;
      null !== a && null !== a.firstContext && (0 !== (a.lanes & b) && (dh = true), a.firstContext = null);
    }
    function eh(a) {
      var b = a._currentValue;
      if (Zg !== a) if (a = { context: a, memoizedValue: b, next: null }, null === Yg) {
        if (null === Xg) throw Error(p(308));
        Yg = a;
        Xg.dependencies = { lanes: 0, firstContext: a };
      } else Yg = Yg.next = a;
      return b;
    }
    var fh = null;
    function gh(a) {
      null === fh ? fh = [a] : fh.push(a);
    }
    function hh(a, b, c, d) {
      var e = b.interleaved;
      null === e ? (c.next = c, gh(b)) : (c.next = e.next, e.next = c);
      b.interleaved = c;
      return ih(a, d);
    }
    function ih(a, b) {
      a.lanes |= b;
      var c = a.alternate;
      null !== c && (c.lanes |= b);
      c = a;
      for (a = a.return; null !== a; ) a.childLanes |= b, c = a.alternate, null !== c && (c.childLanes |= b), c = a, a = a.return;
      return 3 === c.tag ? c.stateNode : null;
    }
    var jh = false;
    function kh(a) {
      a.updateQueue = { baseState: a.memoizedState, firstBaseUpdate: null, lastBaseUpdate: null, shared: { pending: null, interleaved: null, lanes: 0 }, effects: null };
    }
    function lh(a, b) {
      a = a.updateQueue;
      b.updateQueue === a && (b.updateQueue = { baseState: a.baseState, firstBaseUpdate: a.firstBaseUpdate, lastBaseUpdate: a.lastBaseUpdate, shared: a.shared, effects: a.effects });
    }
    function mh(a, b) {
      return { eventTime: a, lane: b, tag: 0, payload: null, callback: null, next: null };
    }
    function nh(a, b, c) {
      var d = a.updateQueue;
      if (null === d) return null;
      d = d.shared;
      if (0 !== (K & 2)) {
        var e = d.pending;
        null === e ? b.next = b : (b.next = e.next, e.next = b);
        d.pending = b;
        return ih(a, c);
      }
      e = d.interleaved;
      null === e ? (b.next = b, gh(d)) : (b.next = e.next, e.next = b);
      d.interleaved = b;
      return ih(a, c);
    }
    function oh(a, b, c) {
      b = b.updateQueue;
      if (null !== b && (b = b.shared, 0 !== (c & 4194240))) {
        var d = b.lanes;
        d &= a.pendingLanes;
        c |= d;
        b.lanes = c;
        Cc(a, c);
      }
    }
    function ph(a, b) {
      var c = a.updateQueue, d = a.alternate;
      if (null !== d && (d = d.updateQueue, c === d)) {
        var e = null, f = null;
        c = c.firstBaseUpdate;
        if (null !== c) {
          do {
            var g = { eventTime: c.eventTime, lane: c.lane, tag: c.tag, payload: c.payload, callback: c.callback, next: null };
            null === f ? e = f = g : f = f.next = g;
            c = c.next;
          } while (null !== c);
          null === f ? e = f = b : f = f.next = b;
        } else e = f = b;
        c = { baseState: d.baseState, firstBaseUpdate: e, lastBaseUpdate: f, shared: d.shared, effects: d.effects };
        a.updateQueue = c;
        return;
      }
      a = c.lastBaseUpdate;
      null === a ? c.firstBaseUpdate = b : a.next = b;
      c.lastBaseUpdate = b;
    }
    function qh(a, b, c, d) {
      var e = a.updateQueue;
      jh = false;
      var f = e.firstBaseUpdate, g = e.lastBaseUpdate, h = e.shared.pending;
      if (null !== h) {
        e.shared.pending = null;
        var k = h, l = k.next;
        k.next = null;
        null === g ? f = l : g.next = l;
        g = k;
        var m = a.alternate;
        null !== m && (m = m.updateQueue, h = m.lastBaseUpdate, h !== g && (null === h ? m.firstBaseUpdate = l : h.next = l, m.lastBaseUpdate = k));
      }
      if (null !== f) {
        var q = e.baseState;
        g = 0;
        m = l = k = null;
        h = f;
        do {
          var r2 = h.lane, y = h.eventTime;
          if ((d & r2) === r2) {
            null !== m && (m = m.next = {
              eventTime: y,
              lane: 0,
              tag: h.tag,
              payload: h.payload,
              callback: h.callback,
              next: null
            });
            a: {
              var n = a, t = h;
              r2 = b;
              y = c;
              switch (t.tag) {
                case 1:
                  n = t.payload;
                  if ("function" === typeof n) {
                    q = n.call(y, q, r2);
                    break a;
                  }
                  q = n;
                  break a;
                case 3:
                  n.flags = n.flags & -65537 | 128;
                case 0:
                  n = t.payload;
                  r2 = "function" === typeof n ? n.call(y, q, r2) : n;
                  if (null === r2 || void 0 === r2) break a;
                  q = A({}, q, r2);
                  break a;
                case 2:
                  jh = true;
              }
            }
            null !== h.callback && 0 !== h.lane && (a.flags |= 64, r2 = e.effects, null === r2 ? e.effects = [h] : r2.push(h));
          } else y = { eventTime: y, lane: r2, tag: h.tag, payload: h.payload, callback: h.callback, next: null }, null === m ? (l = m = y, k = q) : m = m.next = y, g |= r2;
          h = h.next;
          if (null === h) if (h = e.shared.pending, null === h) break;
          else r2 = h, h = r2.next, r2.next = null, e.lastBaseUpdate = r2, e.shared.pending = null;
        } while (1);
        null === m && (k = q);
        e.baseState = k;
        e.firstBaseUpdate = l;
        e.lastBaseUpdate = m;
        b = e.shared.interleaved;
        if (null !== b) {
          e = b;
          do
            g |= e.lane, e = e.next;
          while (e !== b);
        } else null === f && (e.shared.lanes = 0);
        rh |= g;
        a.lanes = g;
        a.memoizedState = q;
      }
    }
    function sh(a, b, c) {
      a = b.effects;
      b.effects = null;
      if (null !== a) for (b = 0; b < a.length; b++) {
        var d = a[b], e = d.callback;
        if (null !== e) {
          d.callback = null;
          d = c;
          if ("function" !== typeof e) throw Error(p(191, e));
          e.call(d);
        }
      }
    }
    var th = {}, uh = Uf(th), vh = Uf(th), wh = Uf(th);
    function xh(a) {
      if (a === th) throw Error(p(174));
      return a;
    }
    function yh(a, b) {
      G(wh, b);
      G(vh, a);
      G(uh, th);
      a = b.nodeType;
      switch (a) {
        case 9:
        case 11:
          b = (b = b.documentElement) ? b.namespaceURI : lb(null, "");
          break;
        default:
          a = 8 === a ? b.parentNode : b, b = a.namespaceURI || null, a = a.tagName, b = lb(b, a);
      }
      E(uh);
      G(uh, b);
    }
    function zh() {
      E(uh);
      E(vh);
      E(wh);
    }
    function Ah(a) {
      xh(wh.current);
      var b = xh(uh.current);
      var c = lb(b, a.type);
      b !== c && (G(vh, a), G(uh, c));
    }
    function Bh(a) {
      vh.current === a && (E(uh), E(vh));
    }
    var L = Uf(0);
    function Ch(a) {
      for (var b = a; null !== b; ) {
        if (13 === b.tag) {
          var c = b.memoizedState;
          if (null !== c && (c = c.dehydrated, null === c || "$?" === c.data || "$!" === c.data)) return b;
        } else if (19 === b.tag && void 0 !== b.memoizedProps.revealOrder) {
          if (0 !== (b.flags & 128)) return b;
        } else if (null !== b.child) {
          b.child.return = b;
          b = b.child;
          continue;
        }
        if (b === a) break;
        for (; null === b.sibling; ) {
          if (null === b.return || b.return === a) return null;
          b = b.return;
        }
        b.sibling.return = b.return;
        b = b.sibling;
      }
      return null;
    }
    var Dh = [];
    function Eh() {
      for (var a = 0; a < Dh.length; a++) Dh[a]._workInProgressVersionPrimary = null;
      Dh.length = 0;
    }
    var Fh = ua.ReactCurrentDispatcher, Gh = ua.ReactCurrentBatchConfig, Hh = 0, M = null, N = null, O = null, Ih = false, Jh = false, Kh = 0, Lh = 0;
    function P() {
      throw Error(p(321));
    }
    function Mh(a, b) {
      if (null === b) return false;
      for (var c = 0; c < b.length && c < a.length; c++) if (!He(a[c], b[c])) return false;
      return true;
    }
    function Nh(a, b, c, d, e, f) {
      Hh = f;
      M = b;
      b.memoizedState = null;
      b.updateQueue = null;
      b.lanes = 0;
      Fh.current = null === a || null === a.memoizedState ? Oh : Ph;
      a = c(d, e);
      if (Jh) {
        f = 0;
        do {
          Jh = false;
          Kh = 0;
          if (25 <= f) throw Error(p(301));
          f += 1;
          O = N = null;
          b.updateQueue = null;
          Fh.current = Qh;
          a = c(d, e);
        } while (Jh);
      }
      Fh.current = Rh;
      b = null !== N && null !== N.next;
      Hh = 0;
      O = N = M = null;
      Ih = false;
      if (b) throw Error(p(300));
      return a;
    }
    function Sh() {
      var a = 0 !== Kh;
      Kh = 0;
      return a;
    }
    function Th() {
      var a = { memoizedState: null, baseState: null, baseQueue: null, queue: null, next: null };
      null === O ? M.memoizedState = O = a : O = O.next = a;
      return O;
    }
    function Uh() {
      if (null === N) {
        var a = M.alternate;
        a = null !== a ? a.memoizedState : null;
      } else a = N.next;
      var b = null === O ? M.memoizedState : O.next;
      if (null !== b) O = b, N = a;
      else {
        if (null === a) throw Error(p(310));
        N = a;
        a = { memoizedState: N.memoizedState, baseState: N.baseState, baseQueue: N.baseQueue, queue: N.queue, next: null };
        null === O ? M.memoizedState = O = a : O = O.next = a;
      }
      return O;
    }
    function Vh(a, b) {
      return "function" === typeof b ? b(a) : b;
    }
    function Wh(a) {
      var b = Uh(), c = b.queue;
      if (null === c) throw Error(p(311));
      c.lastRenderedReducer = a;
      var d = N, e = d.baseQueue, f = c.pending;
      if (null !== f) {
        if (null !== e) {
          var g = e.next;
          e.next = f.next;
          f.next = g;
        }
        d.baseQueue = e = f;
        c.pending = null;
      }
      if (null !== e) {
        f = e.next;
        d = d.baseState;
        var h = g = null, k = null, l = f;
        do {
          var m = l.lane;
          if ((Hh & m) === m) null !== k && (k = k.next = { lane: 0, action: l.action, hasEagerState: l.hasEagerState, eagerState: l.eagerState, next: null }), d = l.hasEagerState ? l.eagerState : a(d, l.action);
          else {
            var q = {
              lane: m,
              action: l.action,
              hasEagerState: l.hasEagerState,
              eagerState: l.eagerState,
              next: null
            };
            null === k ? (h = k = q, g = d) : k = k.next = q;
            M.lanes |= m;
            rh |= m;
          }
          l = l.next;
        } while (null !== l && l !== f);
        null === k ? g = d : k.next = h;
        He(d, b.memoizedState) || (dh = true);
        b.memoizedState = d;
        b.baseState = g;
        b.baseQueue = k;
        c.lastRenderedState = d;
      }
      a = c.interleaved;
      if (null !== a) {
        e = a;
        do
          f = e.lane, M.lanes |= f, rh |= f, e = e.next;
        while (e !== a);
      } else null === e && (c.lanes = 0);
      return [b.memoizedState, c.dispatch];
    }
    function Xh(a) {
      var b = Uh(), c = b.queue;
      if (null === c) throw Error(p(311));
      c.lastRenderedReducer = a;
      var d = c.dispatch, e = c.pending, f = b.memoizedState;
      if (null !== e) {
        c.pending = null;
        var g = e = e.next;
        do
          f = a(f, g.action), g = g.next;
        while (g !== e);
        He(f, b.memoizedState) || (dh = true);
        b.memoizedState = f;
        null === b.baseQueue && (b.baseState = f);
        c.lastRenderedState = f;
      }
      return [f, d];
    }
    function Yh() {
    }
    function Zh(a, b) {
      var c = M, d = Uh(), e = b(), f = !He(d.memoizedState, e);
      f && (d.memoizedState = e, dh = true);
      d = d.queue;
      $h(ai.bind(null, c, d, a), [a]);
      if (d.getSnapshot !== b || f || null !== O && O.memoizedState.tag & 1) {
        c.flags |= 2048;
        bi(9, ci.bind(null, c, d, e, b), void 0, null);
        if (null === Q) throw Error(p(349));
        0 !== (Hh & 30) || di(c, b, e);
      }
      return e;
    }
    function di(a, b, c) {
      a.flags |= 16384;
      a = { getSnapshot: b, value: c };
      b = M.updateQueue;
      null === b ? (b = { lastEffect: null, stores: null }, M.updateQueue = b, b.stores = [a]) : (c = b.stores, null === c ? b.stores = [a] : c.push(a));
    }
    function ci(a, b, c, d) {
      b.value = c;
      b.getSnapshot = d;
      ei(b) && fi(a);
    }
    function ai(a, b, c) {
      return c(function() {
        ei(b) && fi(a);
      });
    }
    function ei(a) {
      var b = a.getSnapshot;
      a = a.value;
      try {
        var c = b();
        return !He(a, c);
      } catch (d) {
        return true;
      }
    }
    function fi(a) {
      var b = ih(a, 1);
      null !== b && gi(b, a, 1, -1);
    }
    function hi(a) {
      var b = Th();
      "function" === typeof a && (a = a());
      b.memoizedState = b.baseState = a;
      a = { pending: null, interleaved: null, lanes: 0, dispatch: null, lastRenderedReducer: Vh, lastRenderedState: a };
      b.queue = a;
      a = a.dispatch = ii.bind(null, M, a);
      return [b.memoizedState, a];
    }
    function bi(a, b, c, d) {
      a = { tag: a, create: b, destroy: c, deps: d, next: null };
      b = M.updateQueue;
      null === b ? (b = { lastEffect: null, stores: null }, M.updateQueue = b, b.lastEffect = a.next = a) : (c = b.lastEffect, null === c ? b.lastEffect = a.next = a : (d = c.next, c.next = a, a.next = d, b.lastEffect = a));
      return a;
    }
    function ji() {
      return Uh().memoizedState;
    }
    function ki(a, b, c, d) {
      var e = Th();
      M.flags |= a;
      e.memoizedState = bi(1 | b, c, void 0, void 0 === d ? null : d);
    }
    function li(a, b, c, d) {
      var e = Uh();
      d = void 0 === d ? null : d;
      var f = void 0;
      if (null !== N) {
        var g = N.memoizedState;
        f = g.destroy;
        if (null !== d && Mh(d, g.deps)) {
          e.memoizedState = bi(b, c, f, d);
          return;
        }
      }
      M.flags |= a;
      e.memoizedState = bi(1 | b, c, f, d);
    }
    function mi(a, b) {
      return ki(8390656, 8, a, b);
    }
    function $h(a, b) {
      return li(2048, 8, a, b);
    }
    function ni(a, b) {
      return li(4, 2, a, b);
    }
    function oi(a, b) {
      return li(4, 4, a, b);
    }
    function pi(a, b) {
      if ("function" === typeof b) return a = a(), b(a), function() {
        b(null);
      };
      if (null !== b && void 0 !== b) return a = a(), b.current = a, function() {
        b.current = null;
      };
    }
    function qi(a, b, c) {
      c = null !== c && void 0 !== c ? c.concat([a]) : null;
      return li(4, 4, pi.bind(null, b, a), c);
    }
    function ri() {
    }
    function si(a, b) {
      var c = Uh();
      b = void 0 === b ? null : b;
      var d = c.memoizedState;
      if (null !== d && null !== b && Mh(b, d[1])) return d[0];
      c.memoizedState = [a, b];
      return a;
    }
    function ti(a, b) {
      var c = Uh();
      b = void 0 === b ? null : b;
      var d = c.memoizedState;
      if (null !== d && null !== b && Mh(b, d[1])) return d[0];
      a = a();
      c.memoizedState = [a, b];
      return a;
    }
    function ui(a, b, c) {
      if (0 === (Hh & 21)) return a.baseState && (a.baseState = false, dh = true), a.memoizedState = c;
      He(c, b) || (c = yc(), M.lanes |= c, rh |= c, a.baseState = true);
      return b;
    }
    function vi(a, b) {
      var c = C;
      C = 0 !== c && 4 > c ? c : 4;
      a(true);
      var d = Gh.transition;
      Gh.transition = {};
      try {
        a(false), b();
      } finally {
        C = c, Gh.transition = d;
      }
    }
    function wi() {
      return Uh().memoizedState;
    }
    function xi(a, b, c) {
      var d = yi(a);
      c = { lane: d, action: c, hasEagerState: false, eagerState: null, next: null };
      if (zi(a)) Ai(b, c);
      else if (c = hh(a, b, c, d), null !== c) {
        var e = R();
        gi(c, a, d, e);
        Bi(c, b, d);
      }
    }
    function ii(a, b, c) {
      var d = yi(a), e = { lane: d, action: c, hasEagerState: false, eagerState: null, next: null };
      if (zi(a)) Ai(b, e);
      else {
        var f = a.alternate;
        if (0 === a.lanes && (null === f || 0 === f.lanes) && (f = b.lastRenderedReducer, null !== f)) try {
          var g = b.lastRenderedState, h = f(g, c);
          e.hasEagerState = true;
          e.eagerState = h;
          if (He(h, g)) {
            var k = b.interleaved;
            null === k ? (e.next = e, gh(b)) : (e.next = k.next, k.next = e);
            b.interleaved = e;
            return;
          }
        } catch (l) {
        } finally {
        }
        c = hh(a, b, e, d);
        null !== c && (e = R(), gi(c, a, d, e), Bi(c, b, d));
      }
    }
    function zi(a) {
      var b = a.alternate;
      return a === M || null !== b && b === M;
    }
    function Ai(a, b) {
      Jh = Ih = true;
      var c = a.pending;
      null === c ? b.next = b : (b.next = c.next, c.next = b);
      a.pending = b;
    }
    function Bi(a, b, c) {
      if (0 !== (c & 4194240)) {
        var d = b.lanes;
        d &= a.pendingLanes;
        c |= d;
        b.lanes = c;
        Cc(a, c);
      }
    }
    var Rh = { readContext: eh, useCallback: P, useContext: P, useEffect: P, useImperativeHandle: P, useInsertionEffect: P, useLayoutEffect: P, useMemo: P, useReducer: P, useRef: P, useState: P, useDebugValue: P, useDeferredValue: P, useTransition: P, useMutableSource: P, useSyncExternalStore: P, useId: P, unstable_isNewReconciler: false }, Oh = { readContext: eh, useCallback: function(a, b) {
      Th().memoizedState = [a, void 0 === b ? null : b];
      return a;
    }, useContext: eh, useEffect: mi, useImperativeHandle: function(a, b, c) {
      c = null !== c && void 0 !== c ? c.concat([a]) : null;
      return ki(
        4194308,
        4,
        pi.bind(null, b, a),
        c
      );
    }, useLayoutEffect: function(a, b) {
      return ki(4194308, 4, a, b);
    }, useInsertionEffect: function(a, b) {
      return ki(4, 2, a, b);
    }, useMemo: function(a, b) {
      var c = Th();
      b = void 0 === b ? null : b;
      a = a();
      c.memoizedState = [a, b];
      return a;
    }, useReducer: function(a, b, c) {
      var d = Th();
      b = void 0 !== c ? c(b) : b;
      d.memoizedState = d.baseState = b;
      a = { pending: null, interleaved: null, lanes: 0, dispatch: null, lastRenderedReducer: a, lastRenderedState: b };
      d.queue = a;
      a = a.dispatch = xi.bind(null, M, a);
      return [d.memoizedState, a];
    }, useRef: function(a) {
      var b = Th();
      a = { current: a };
      return b.memoizedState = a;
    }, useState: hi, useDebugValue: ri, useDeferredValue: function(a) {
      return Th().memoizedState = a;
    }, useTransition: function() {
      var a = hi(false), b = a[0];
      a = vi.bind(null, a[1]);
      Th().memoizedState = a;
      return [b, a];
    }, useMutableSource: function() {
    }, useSyncExternalStore: function(a, b, c) {
      var d = M, e = Th();
      if (I) {
        if (void 0 === c) throw Error(p(407));
        c = c();
      } else {
        c = b();
        if (null === Q) throw Error(p(349));
        0 !== (Hh & 30) || di(d, b, c);
      }
      e.memoizedState = c;
      var f = { value: c, getSnapshot: b };
      e.queue = f;
      mi(ai.bind(
        null,
        d,
        f,
        a
      ), [a]);
      d.flags |= 2048;
      bi(9, ci.bind(null, d, f, c, b), void 0, null);
      return c;
    }, useId: function() {
      var a = Th(), b = Q.identifierPrefix;
      if (I) {
        var c = sg;
        var d = rg;
        c = (d & ~(1 << 32 - oc(d) - 1)).toString(32) + c;
        b = ":" + b + "R" + c;
        c = Kh++;
        0 < c && (b += "H" + c.toString(32));
        b += ":";
      } else c = Lh++, b = ":" + b + "r" + c.toString(32) + ":";
      return a.memoizedState = b;
    }, unstable_isNewReconciler: false }, Ph = {
      readContext: eh,
      useCallback: si,
      useContext: eh,
      useEffect: $h,
      useImperativeHandle: qi,
      useInsertionEffect: ni,
      useLayoutEffect: oi,
      useMemo: ti,
      useReducer: Wh,
      useRef: ji,
      useState: function() {
        return Wh(Vh);
      },
      useDebugValue: ri,
      useDeferredValue: function(a) {
        var b = Uh();
        return ui(b, N.memoizedState, a);
      },
      useTransition: function() {
        var a = Wh(Vh)[0], b = Uh().memoizedState;
        return [a, b];
      },
      useMutableSource: Yh,
      useSyncExternalStore: Zh,
      useId: wi,
      unstable_isNewReconciler: false
    }, Qh = { readContext: eh, useCallback: si, useContext: eh, useEffect: $h, useImperativeHandle: qi, useInsertionEffect: ni, useLayoutEffect: oi, useMemo: ti, useReducer: Xh, useRef: ji, useState: function() {
      return Xh(Vh);
    }, useDebugValue: ri, useDeferredValue: function(a) {
      var b = Uh();
      return null === N ? b.memoizedState = a : ui(b, N.memoizedState, a);
    }, useTransition: function() {
      var a = Xh(Vh)[0], b = Uh().memoizedState;
      return [a, b];
    }, useMutableSource: Yh, useSyncExternalStore: Zh, useId: wi, unstable_isNewReconciler: false };
    function Ci(a, b) {
      if (a && a.defaultProps) {
        b = A({}, b);
        a = a.defaultProps;
        for (var c in a) void 0 === b[c] && (b[c] = a[c]);
        return b;
      }
      return b;
    }
    function Di(a, b, c, d) {
      b = a.memoizedState;
      c = c(d, b);
      c = null === c || void 0 === c ? b : A({}, b, c);
      a.memoizedState = c;
      0 === a.lanes && (a.updateQueue.baseState = c);
    }
    var Ei = { isMounted: function(a) {
      return (a = a._reactInternals) ? Vb(a) === a : false;
    }, enqueueSetState: function(a, b, c) {
      a = a._reactInternals;
      var d = R(), e = yi(a), f = mh(d, e);
      f.payload = b;
      void 0 !== c && null !== c && (f.callback = c);
      b = nh(a, f, e);
      null !== b && (gi(b, a, e, d), oh(b, a, e));
    }, enqueueReplaceState: function(a, b, c) {
      a = a._reactInternals;
      var d = R(), e = yi(a), f = mh(d, e);
      f.tag = 1;
      f.payload = b;
      void 0 !== c && null !== c && (f.callback = c);
      b = nh(a, f, e);
      null !== b && (gi(b, a, e, d), oh(b, a, e));
    }, enqueueForceUpdate: function(a, b) {
      a = a._reactInternals;
      var c = R(), d = yi(a), e = mh(c, d);
      e.tag = 2;
      void 0 !== b && null !== b && (e.callback = b);
      b = nh(a, e, d);
      null !== b && (gi(b, a, d, c), oh(b, a, d));
    } };
    function Fi(a, b, c, d, e, f, g) {
      a = a.stateNode;
      return "function" === typeof a.shouldComponentUpdate ? a.shouldComponentUpdate(d, f, g) : b.prototype && b.prototype.isPureReactComponent ? !Ie(c, d) || !Ie(e, f) : true;
    }
    function Gi(a, b, c) {
      var d = false, e = Vf;
      var f = b.contextType;
      "object" === typeof f && null !== f ? f = eh(f) : (e = Zf(b) ? Xf : H.current, d = b.contextTypes, f = (d = null !== d && void 0 !== d) ? Yf(a, e) : Vf);
      b = new b(c, f);
      a.memoizedState = null !== b.state && void 0 !== b.state ? b.state : null;
      b.updater = Ei;
      a.stateNode = b;
      b._reactInternals = a;
      d && (a = a.stateNode, a.__reactInternalMemoizedUnmaskedChildContext = e, a.__reactInternalMemoizedMaskedChildContext = f);
      return b;
    }
    function Hi(a, b, c, d) {
      a = b.state;
      "function" === typeof b.componentWillReceiveProps && b.componentWillReceiveProps(c, d);
      "function" === typeof b.UNSAFE_componentWillReceiveProps && b.UNSAFE_componentWillReceiveProps(c, d);
      b.state !== a && Ei.enqueueReplaceState(b, b.state, null);
    }
    function Ii(a, b, c, d) {
      var e = a.stateNode;
      e.props = c;
      e.state = a.memoizedState;
      e.refs = {};
      kh(a);
      var f = b.contextType;
      "object" === typeof f && null !== f ? e.context = eh(f) : (f = Zf(b) ? Xf : H.current, e.context = Yf(a, f));
      e.state = a.memoizedState;
      f = b.getDerivedStateFromProps;
      "function" === typeof f && (Di(a, b, f, c), e.state = a.memoizedState);
      "function" === typeof b.getDerivedStateFromProps || "function" === typeof e.getSnapshotBeforeUpdate || "function" !== typeof e.UNSAFE_componentWillMount && "function" !== typeof e.componentWillMount || (b = e.state, "function" === typeof e.componentWillMount && e.componentWillMount(), "function" === typeof e.UNSAFE_componentWillMount && e.UNSAFE_componentWillMount(), b !== e.state && Ei.enqueueReplaceState(e, e.state, null), qh(a, c, e, d), e.state = a.memoizedState);
      "function" === typeof e.componentDidMount && (a.flags |= 4194308);
    }
    function Ji(a, b) {
      try {
        var c = "", d = b;
        do
          c += Pa(d), d = d.return;
        while (d);
        var e = c;
      } catch (f) {
        e = "\nError generating stack: " + f.message + "\n" + f.stack;
      }
      return { value: a, source: b, stack: e, digest: null };
    }
    function Ki(a, b, c) {
      return { value: a, source: null, stack: null != c ? c : null, digest: null != b ? b : null };
    }
    function Li(a, b) {
      try {
        console.error(b.value);
      } catch (c) {
        setTimeout(function() {
          throw c;
        });
      }
    }
    var Mi = "function" === typeof WeakMap ? WeakMap : Map;
    function Ni(a, b, c) {
      c = mh(-1, c);
      c.tag = 3;
      c.payload = { element: null };
      var d = b.value;
      c.callback = function() {
        Oi || (Oi = true, Pi = d);
        Li(a, b);
      };
      return c;
    }
    function Qi(a, b, c) {
      c = mh(-1, c);
      c.tag = 3;
      var d = a.type.getDerivedStateFromError;
      if ("function" === typeof d) {
        var e = b.value;
        c.payload = function() {
          return d(e);
        };
        c.callback = function() {
          Li(a, b);
        };
      }
      var f = a.stateNode;
      null !== f && "function" === typeof f.componentDidCatch && (c.callback = function() {
        Li(a, b);
        "function" !== typeof d && (null === Ri ? Ri = /* @__PURE__ */ new Set([this]) : Ri.add(this));
        var c2 = b.stack;
        this.componentDidCatch(b.value, { componentStack: null !== c2 ? c2 : "" });
      });
      return c;
    }
    function Si(a, b, c) {
      var d = a.pingCache;
      if (null === d) {
        d = a.pingCache = new Mi();
        var e = /* @__PURE__ */ new Set();
        d.set(b, e);
      } else e = d.get(b), void 0 === e && (e = /* @__PURE__ */ new Set(), d.set(b, e));
      e.has(c) || (e.add(c), a = Ti.bind(null, a, b, c), b.then(a, a));
    }
    function Ui(a) {
      do {
        var b;
        if (b = 13 === a.tag) b = a.memoizedState, b = null !== b ? null !== b.dehydrated ? true : false : true;
        if (b) return a;
        a = a.return;
      } while (null !== a);
      return null;
    }
    function Vi(a, b, c, d, e) {
      if (0 === (a.mode & 1)) return a === b ? a.flags |= 65536 : (a.flags |= 128, c.flags |= 131072, c.flags &= -52805, 1 === c.tag && (null === c.alternate ? c.tag = 17 : (b = mh(-1, 1), b.tag = 2, nh(c, b, 1))), c.lanes |= 1), a;
      a.flags |= 65536;
      a.lanes = e;
      return a;
    }
    var Wi = ua.ReactCurrentOwner, dh = false;
    function Xi(a, b, c, d) {
      b.child = null === a ? Vg(b, null, c, d) : Ug(b, a.child, c, d);
    }
    function Yi(a, b, c, d, e) {
      c = c.render;
      var f = b.ref;
      ch(b, e);
      d = Nh(a, b, c, d, f, e);
      c = Sh();
      if (null !== a && !dh) return b.updateQueue = a.updateQueue, b.flags &= -2053, a.lanes &= ~e, Zi(a, b, e);
      I && c && vg(b);
      b.flags |= 1;
      Xi(a, b, d, e);
      return b.child;
    }
    function $i(a, b, c, d, e) {
      if (null === a) {
        var f = c.type;
        if ("function" === typeof f && !aj(f) && void 0 === f.defaultProps && null === c.compare && void 0 === c.defaultProps) return b.tag = 15, b.type = f, bj(a, b, f, d, e);
        a = Rg(c.type, null, d, b, b.mode, e);
        a.ref = b.ref;
        a.return = b;
        return b.child = a;
      }
      f = a.child;
      if (0 === (a.lanes & e)) {
        var g = f.memoizedProps;
        c = c.compare;
        c = null !== c ? c : Ie;
        if (c(g, d) && a.ref === b.ref) return Zi(a, b, e);
      }
      b.flags |= 1;
      a = Pg(f, d);
      a.ref = b.ref;
      a.return = b;
      return b.child = a;
    }
    function bj(a, b, c, d, e) {
      if (null !== a) {
        var f = a.memoizedProps;
        if (Ie(f, d) && a.ref === b.ref) if (dh = false, b.pendingProps = d = f, 0 !== (a.lanes & e)) 0 !== (a.flags & 131072) && (dh = true);
        else return b.lanes = a.lanes, Zi(a, b, e);
      }
      return cj(a, b, c, d, e);
    }
    function dj(a, b, c) {
      var d = b.pendingProps, e = d.children, f = null !== a ? a.memoizedState : null;
      if ("hidden" === d.mode) if (0 === (b.mode & 1)) b.memoizedState = { baseLanes: 0, cachePool: null, transitions: null }, G(ej, fj), fj |= c;
      else {
        if (0 === (c & 1073741824)) return a = null !== f ? f.baseLanes | c : c, b.lanes = b.childLanes = 1073741824, b.memoizedState = { baseLanes: a, cachePool: null, transitions: null }, b.updateQueue = null, G(ej, fj), fj |= a, null;
        b.memoizedState = { baseLanes: 0, cachePool: null, transitions: null };
        d = null !== f ? f.baseLanes : c;
        G(ej, fj);
        fj |= d;
      }
      else null !== f ? (d = f.baseLanes | c, b.memoizedState = null) : d = c, G(ej, fj), fj |= d;
      Xi(a, b, e, c);
      return b.child;
    }
    function gj(a, b) {
      var c = b.ref;
      if (null === a && null !== c || null !== a && a.ref !== c) b.flags |= 512, b.flags |= 2097152;
    }
    function cj(a, b, c, d, e) {
      var f = Zf(c) ? Xf : H.current;
      f = Yf(b, f);
      ch(b, e);
      c = Nh(a, b, c, d, f, e);
      d = Sh();
      if (null !== a && !dh) return b.updateQueue = a.updateQueue, b.flags &= -2053, a.lanes &= ~e, Zi(a, b, e);
      I && d && vg(b);
      b.flags |= 1;
      Xi(a, b, c, e);
      return b.child;
    }
    function hj(a, b, c, d, e) {
      if (Zf(c)) {
        var f = true;
        cg(b);
      } else f = false;
      ch(b, e);
      if (null === b.stateNode) ij(a, b), Gi(b, c, d), Ii(b, c, d, e), d = true;
      else if (null === a) {
        var g = b.stateNode, h = b.memoizedProps;
        g.props = h;
        var k = g.context, l = c.contextType;
        "object" === typeof l && null !== l ? l = eh(l) : (l = Zf(c) ? Xf : H.current, l = Yf(b, l));
        var m = c.getDerivedStateFromProps, q = "function" === typeof m || "function" === typeof g.getSnapshotBeforeUpdate;
        q || "function" !== typeof g.UNSAFE_componentWillReceiveProps && "function" !== typeof g.componentWillReceiveProps || (h !== d || k !== l) && Hi(b, g, d, l);
        jh = false;
        var r2 = b.memoizedState;
        g.state = r2;
        qh(b, d, g, e);
        k = b.memoizedState;
        h !== d || r2 !== k || Wf.current || jh ? ("function" === typeof m && (Di(b, c, m, d), k = b.memoizedState), (h = jh || Fi(b, c, h, d, r2, k, l)) ? (q || "function" !== typeof g.UNSAFE_componentWillMount && "function" !== typeof g.componentWillMount || ("function" === typeof g.componentWillMount && g.componentWillMount(), "function" === typeof g.UNSAFE_componentWillMount && g.UNSAFE_componentWillMount()), "function" === typeof g.componentDidMount && (b.flags |= 4194308)) : ("function" === typeof g.componentDidMount && (b.flags |= 4194308), b.memoizedProps = d, b.memoizedState = k), g.props = d, g.state = k, g.context = l, d = h) : ("function" === typeof g.componentDidMount && (b.flags |= 4194308), d = false);
      } else {
        g = b.stateNode;
        lh(a, b);
        h = b.memoizedProps;
        l = b.type === b.elementType ? h : Ci(b.type, h);
        g.props = l;
        q = b.pendingProps;
        r2 = g.context;
        k = c.contextType;
        "object" === typeof k && null !== k ? k = eh(k) : (k = Zf(c) ? Xf : H.current, k = Yf(b, k));
        var y = c.getDerivedStateFromProps;
        (m = "function" === typeof y || "function" === typeof g.getSnapshotBeforeUpdate) || "function" !== typeof g.UNSAFE_componentWillReceiveProps && "function" !== typeof g.componentWillReceiveProps || (h !== q || r2 !== k) && Hi(b, g, d, k);
        jh = false;
        r2 = b.memoizedState;
        g.state = r2;
        qh(b, d, g, e);
        var n = b.memoizedState;
        h !== q || r2 !== n || Wf.current || jh ? ("function" === typeof y && (Di(b, c, y, d), n = b.memoizedState), (l = jh || Fi(b, c, l, d, r2, n, k) || false) ? (m || "function" !== typeof g.UNSAFE_componentWillUpdate && "function" !== typeof g.componentWillUpdate || ("function" === typeof g.componentWillUpdate && g.componentWillUpdate(d, n, k), "function" === typeof g.UNSAFE_componentWillUpdate && g.UNSAFE_componentWillUpdate(d, n, k)), "function" === typeof g.componentDidUpdate && (b.flags |= 4), "function" === typeof g.getSnapshotBeforeUpdate && (b.flags |= 1024)) : ("function" !== typeof g.componentDidUpdate || h === a.memoizedProps && r2 === a.memoizedState || (b.flags |= 4), "function" !== typeof g.getSnapshotBeforeUpdate || h === a.memoizedProps && r2 === a.memoizedState || (b.flags |= 1024), b.memoizedProps = d, b.memoizedState = n), g.props = d, g.state = n, g.context = k, d = l) : ("function" !== typeof g.componentDidUpdate || h === a.memoizedProps && r2 === a.memoizedState || (b.flags |= 4), "function" !== typeof g.getSnapshotBeforeUpdate || h === a.memoizedProps && r2 === a.memoizedState || (b.flags |= 1024), d = false);
      }
      return jj(a, b, c, d, f, e);
    }
    function jj(a, b, c, d, e, f) {
      gj(a, b);
      var g = 0 !== (b.flags & 128);
      if (!d && !g) return e && dg(b, c, false), Zi(a, b, f);
      d = b.stateNode;
      Wi.current = b;
      var h = g && "function" !== typeof c.getDerivedStateFromError ? null : d.render();
      b.flags |= 1;
      null !== a && g ? (b.child = Ug(b, a.child, null, f), b.child = Ug(b, null, h, f)) : Xi(a, b, h, f);
      b.memoizedState = d.state;
      e && dg(b, c, true);
      return b.child;
    }
    function kj(a) {
      var b = a.stateNode;
      b.pendingContext ? ag(a, b.pendingContext, b.pendingContext !== b.context) : b.context && ag(a, b.context, false);
      yh(a, b.containerInfo);
    }
    function lj(a, b, c, d, e) {
      Ig();
      Jg(e);
      b.flags |= 256;
      Xi(a, b, c, d);
      return b.child;
    }
    var mj = { dehydrated: null, treeContext: null, retryLane: 0 };
    function nj(a) {
      return { baseLanes: a, cachePool: null, transitions: null };
    }
    function oj(a, b, c) {
      var d = b.pendingProps, e = L.current, f = false, g = 0 !== (b.flags & 128), h;
      (h = g) || (h = null !== a && null === a.memoizedState ? false : 0 !== (e & 2));
      if (h) f = true, b.flags &= -129;
      else if (null === a || null !== a.memoizedState) e |= 1;
      G(L, e & 1);
      if (null === a) {
        Eg(b);
        a = b.memoizedState;
        if (null !== a && (a = a.dehydrated, null !== a)) return 0 === (b.mode & 1) ? b.lanes = 1 : "$!" === a.data ? b.lanes = 8 : b.lanes = 1073741824, null;
        g = d.children;
        a = d.fallback;
        return f ? (d = b.mode, f = b.child, g = { mode: "hidden", children: g }, 0 === (d & 1) && null !== f ? (f.childLanes = 0, f.pendingProps = g) : f = pj(g, d, 0, null), a = Tg(a, d, c, null), f.return = b, a.return = b, f.sibling = a, b.child = f, b.child.memoizedState = nj(c), b.memoizedState = mj, a) : qj(b, g);
      }
      e = a.memoizedState;
      if (null !== e && (h = e.dehydrated, null !== h)) return rj(a, b, g, d, h, e, c);
      if (f) {
        f = d.fallback;
        g = b.mode;
        e = a.child;
        h = e.sibling;
        var k = { mode: "hidden", children: d.children };
        0 === (g & 1) && b.child !== e ? (d = b.child, d.childLanes = 0, d.pendingProps = k, b.deletions = null) : (d = Pg(e, k), d.subtreeFlags = e.subtreeFlags & 14680064);
        null !== h ? f = Pg(h, f) : (f = Tg(f, g, c, null), f.flags |= 2);
        f.return = b;
        d.return = b;
        d.sibling = f;
        b.child = d;
        d = f;
        f = b.child;
        g = a.child.memoizedState;
        g = null === g ? nj(c) : { baseLanes: g.baseLanes | c, cachePool: null, transitions: g.transitions };
        f.memoizedState = g;
        f.childLanes = a.childLanes & ~c;
        b.memoizedState = mj;
        return d;
      }
      f = a.child;
      a = f.sibling;
      d = Pg(f, { mode: "visible", children: d.children });
      0 === (b.mode & 1) && (d.lanes = c);
      d.return = b;
      d.sibling = null;
      null !== a && (c = b.deletions, null === c ? (b.deletions = [a], b.flags |= 16) : c.push(a));
      b.child = d;
      b.memoizedState = null;
      return d;
    }
    function qj(a, b) {
      b = pj({ mode: "visible", children: b }, a.mode, 0, null);
      b.return = a;
      return a.child = b;
    }
    function sj(a, b, c, d) {
      null !== d && Jg(d);
      Ug(b, a.child, null, c);
      a = qj(b, b.pendingProps.children);
      a.flags |= 2;
      b.memoizedState = null;
      return a;
    }
    function rj(a, b, c, d, e, f, g) {
      if (c) {
        if (b.flags & 256) return b.flags &= -257, d = Ki(Error(p(422))), sj(a, b, g, d);
        if (null !== b.memoizedState) return b.child = a.child, b.flags |= 128, null;
        f = d.fallback;
        e = b.mode;
        d = pj({ mode: "visible", children: d.children }, e, 0, null);
        f = Tg(f, e, g, null);
        f.flags |= 2;
        d.return = b;
        f.return = b;
        d.sibling = f;
        b.child = d;
        0 !== (b.mode & 1) && Ug(b, a.child, null, g);
        b.child.memoizedState = nj(g);
        b.memoizedState = mj;
        return f;
      }
      if (0 === (b.mode & 1)) return sj(a, b, g, null);
      if ("$!" === e.data) {
        d = e.nextSibling && e.nextSibling.dataset;
        if (d) var h = d.dgst;
        d = h;
        f = Error(p(419));
        d = Ki(f, d, void 0);
        return sj(a, b, g, d);
      }
      h = 0 !== (g & a.childLanes);
      if (dh || h) {
        d = Q;
        if (null !== d) {
          switch (g & -g) {
            case 4:
              e = 2;
              break;
            case 16:
              e = 8;
              break;
            case 64:
            case 128:
            case 256:
            case 512:
            case 1024:
            case 2048:
            case 4096:
            case 8192:
            case 16384:
            case 32768:
            case 65536:
            case 131072:
            case 262144:
            case 524288:
            case 1048576:
            case 2097152:
            case 4194304:
            case 8388608:
            case 16777216:
            case 33554432:
            case 67108864:
              e = 32;
              break;
            case 536870912:
              e = 268435456;
              break;
            default:
              e = 0;
          }
          e = 0 !== (e & (d.suspendedLanes | g)) ? 0 : e;
          0 !== e && e !== f.retryLane && (f.retryLane = e, ih(a, e), gi(d, a, e, -1));
        }
        tj();
        d = Ki(Error(p(421)));
        return sj(a, b, g, d);
      }
      if ("$?" === e.data) return b.flags |= 128, b.child = a.child, b = uj.bind(null, a), e._reactRetry = b, null;
      a = f.treeContext;
      yg = Lf(e.nextSibling);
      xg = b;
      I = true;
      zg = null;
      null !== a && (og[pg++] = rg, og[pg++] = sg, og[pg++] = qg, rg = a.id, sg = a.overflow, qg = b);
      b = qj(b, d.children);
      b.flags |= 4096;
      return b;
    }
    function vj(a, b, c) {
      a.lanes |= b;
      var d = a.alternate;
      null !== d && (d.lanes |= b);
      bh(a.return, b, c);
    }
    function wj(a, b, c, d, e) {
      var f = a.memoizedState;
      null === f ? a.memoizedState = { isBackwards: b, rendering: null, renderingStartTime: 0, last: d, tail: c, tailMode: e } : (f.isBackwards = b, f.rendering = null, f.renderingStartTime = 0, f.last = d, f.tail = c, f.tailMode = e);
    }
    function xj(a, b, c) {
      var d = b.pendingProps, e = d.revealOrder, f = d.tail;
      Xi(a, b, d.children, c);
      d = L.current;
      if (0 !== (d & 2)) d = d & 1 | 2, b.flags |= 128;
      else {
        if (null !== a && 0 !== (a.flags & 128)) a: for (a = b.child; null !== a; ) {
          if (13 === a.tag) null !== a.memoizedState && vj(a, c, b);
          else if (19 === a.tag) vj(a, c, b);
          else if (null !== a.child) {
            a.child.return = a;
            a = a.child;
            continue;
          }
          if (a === b) break a;
          for (; null === a.sibling; ) {
            if (null === a.return || a.return === b) break a;
            a = a.return;
          }
          a.sibling.return = a.return;
          a = a.sibling;
        }
        d &= 1;
      }
      G(L, d);
      if (0 === (b.mode & 1)) b.memoizedState = null;
      else switch (e) {
        case "forwards":
          c = b.child;
          for (e = null; null !== c; ) a = c.alternate, null !== a && null === Ch(a) && (e = c), c = c.sibling;
          c = e;
          null === c ? (e = b.child, b.child = null) : (e = c.sibling, c.sibling = null);
          wj(b, false, e, c, f);
          break;
        case "backwards":
          c = null;
          e = b.child;
          for (b.child = null; null !== e; ) {
            a = e.alternate;
            if (null !== a && null === Ch(a)) {
              b.child = e;
              break;
            }
            a = e.sibling;
            e.sibling = c;
            c = e;
            e = a;
          }
          wj(b, true, c, null, f);
          break;
        case "together":
          wj(b, false, null, null, void 0);
          break;
        default:
          b.memoizedState = null;
      }
      return b.child;
    }
    function ij(a, b) {
      0 === (b.mode & 1) && null !== a && (a.alternate = null, b.alternate = null, b.flags |= 2);
    }
    function Zi(a, b, c) {
      null !== a && (b.dependencies = a.dependencies);
      rh |= b.lanes;
      if (0 === (c & b.childLanes)) return null;
      if (null !== a && b.child !== a.child) throw Error(p(153));
      if (null !== b.child) {
        a = b.child;
        c = Pg(a, a.pendingProps);
        b.child = c;
        for (c.return = b; null !== a.sibling; ) a = a.sibling, c = c.sibling = Pg(a, a.pendingProps), c.return = b;
        c.sibling = null;
      }
      return b.child;
    }
    function yj(a, b, c) {
      switch (b.tag) {
        case 3:
          kj(b);
          Ig();
          break;
        case 5:
          Ah(b);
          break;
        case 1:
          Zf(b.type) && cg(b);
          break;
        case 4:
          yh(b, b.stateNode.containerInfo);
          break;
        case 10:
          var d = b.type._context, e = b.memoizedProps.value;
          G(Wg, d._currentValue);
          d._currentValue = e;
          break;
        case 13:
          d = b.memoizedState;
          if (null !== d) {
            if (null !== d.dehydrated) return G(L, L.current & 1), b.flags |= 128, null;
            if (0 !== (c & b.child.childLanes)) return oj(a, b, c);
            G(L, L.current & 1);
            a = Zi(a, b, c);
            return null !== a ? a.sibling : null;
          }
          G(L, L.current & 1);
          break;
        case 19:
          d = 0 !== (c & b.childLanes);
          if (0 !== (a.flags & 128)) {
            if (d) return xj(a, b, c);
            b.flags |= 128;
          }
          e = b.memoizedState;
          null !== e && (e.rendering = null, e.tail = null, e.lastEffect = null);
          G(L, L.current);
          if (d) break;
          else return null;
        case 22:
        case 23:
          return b.lanes = 0, dj(a, b, c);
      }
      return Zi(a, b, c);
    }
    var zj, Aj, Bj, Cj;
    zj = function(a, b) {
      for (var c = b.child; null !== c; ) {
        if (5 === c.tag || 6 === c.tag) a.appendChild(c.stateNode);
        else if (4 !== c.tag && null !== c.child) {
          c.child.return = c;
          c = c.child;
          continue;
        }
        if (c === b) break;
        for (; null === c.sibling; ) {
          if (null === c.return || c.return === b) return;
          c = c.return;
        }
        c.sibling.return = c.return;
        c = c.sibling;
      }
    };
    Aj = function() {
    };
    Bj = function(a, b, c, d) {
      var e = a.memoizedProps;
      if (e !== d) {
        a = b.stateNode;
        xh(uh.current);
        var f = null;
        switch (c) {
          case "input":
            e = Ya(a, e);
            d = Ya(a, d);
            f = [];
            break;
          case "select":
            e = A({}, e, { value: void 0 });
            d = A({}, d, { value: void 0 });
            f = [];
            break;
          case "textarea":
            e = gb(a, e);
            d = gb(a, d);
            f = [];
            break;
          default:
            "function" !== typeof e.onClick && "function" === typeof d.onClick && (a.onclick = Bf);
        }
        ub(c, d);
        var g;
        c = null;
        for (l in e) if (!d.hasOwnProperty(l) && e.hasOwnProperty(l) && null != e[l]) if ("style" === l) {
          var h = e[l];
          for (g in h) h.hasOwnProperty(g) && (c || (c = {}), c[g] = "");
        } else "dangerouslySetInnerHTML" !== l && "children" !== l && "suppressContentEditableWarning" !== l && "suppressHydrationWarning" !== l && "autoFocus" !== l && (ea.hasOwnProperty(l) ? f || (f = []) : (f = f || []).push(l, null));
        for (l in d) {
          var k = d[l];
          h = null != e ? e[l] : void 0;
          if (d.hasOwnProperty(l) && k !== h && (null != k || null != h)) if ("style" === l) if (h) {
            for (g in h) !h.hasOwnProperty(g) || k && k.hasOwnProperty(g) || (c || (c = {}), c[g] = "");
            for (g in k) k.hasOwnProperty(g) && h[g] !== k[g] && (c || (c = {}), c[g] = k[g]);
          } else c || (f || (f = []), f.push(
            l,
            c
          )), c = k;
          else "dangerouslySetInnerHTML" === l ? (k = k ? k.__html : void 0, h = h ? h.__html : void 0, null != k && h !== k && (f = f || []).push(l, k)) : "children" === l ? "string" !== typeof k && "number" !== typeof k || (f = f || []).push(l, "" + k) : "suppressContentEditableWarning" !== l && "suppressHydrationWarning" !== l && (ea.hasOwnProperty(l) ? (null != k && "onScroll" === l && D("scroll", a), f || h === k || (f = [])) : (f = f || []).push(l, k));
        }
        c && (f = f || []).push("style", c);
        var l = f;
        if (b.updateQueue = l) b.flags |= 4;
      }
    };
    Cj = function(a, b, c, d) {
      c !== d && (b.flags |= 4);
    };
    function Dj(a, b) {
      if (!I) switch (a.tailMode) {
        case "hidden":
          b = a.tail;
          for (var c = null; null !== b; ) null !== b.alternate && (c = b), b = b.sibling;
          null === c ? a.tail = null : c.sibling = null;
          break;
        case "collapsed":
          c = a.tail;
          for (var d = null; null !== c; ) null !== c.alternate && (d = c), c = c.sibling;
          null === d ? b || null === a.tail ? a.tail = null : a.tail.sibling = null : d.sibling = null;
      }
    }
    function S(a) {
      var b = null !== a.alternate && a.alternate.child === a.child, c = 0, d = 0;
      if (b) for (var e = a.child; null !== e; ) c |= e.lanes | e.childLanes, d |= e.subtreeFlags & 14680064, d |= e.flags & 14680064, e.return = a, e = e.sibling;
      else for (e = a.child; null !== e; ) c |= e.lanes | e.childLanes, d |= e.subtreeFlags, d |= e.flags, e.return = a, e = e.sibling;
      a.subtreeFlags |= d;
      a.childLanes = c;
      return b;
    }
    function Ej(a, b, c) {
      var d = b.pendingProps;
      wg(b);
      switch (b.tag) {
        case 2:
        case 16:
        case 15:
        case 0:
        case 11:
        case 7:
        case 8:
        case 12:
        case 9:
        case 14:
          return S(b), null;
        case 1:
          return Zf(b.type) && $f(), S(b), null;
        case 3:
          d = b.stateNode;
          zh();
          E(Wf);
          E(H);
          Eh();
          d.pendingContext && (d.context = d.pendingContext, d.pendingContext = null);
          if (null === a || null === a.child) Gg(b) ? b.flags |= 4 : null === a || a.memoizedState.isDehydrated && 0 === (b.flags & 256) || (b.flags |= 1024, null !== zg && (Fj(zg), zg = null));
          Aj(a, b);
          S(b);
          return null;
        case 5:
          Bh(b);
          var e = xh(wh.current);
          c = b.type;
          if (null !== a && null != b.stateNode) Bj(a, b, c, d, e), a.ref !== b.ref && (b.flags |= 512, b.flags |= 2097152);
          else {
            if (!d) {
              if (null === b.stateNode) throw Error(p(166));
              S(b);
              return null;
            }
            a = xh(uh.current);
            if (Gg(b)) {
              d = b.stateNode;
              c = b.type;
              var f = b.memoizedProps;
              d[Of] = b;
              d[Pf] = f;
              a = 0 !== (b.mode & 1);
              switch (c) {
                case "dialog":
                  D("cancel", d);
                  D("close", d);
                  break;
                case "iframe":
                case "object":
                case "embed":
                  D("load", d);
                  break;
                case "video":
                case "audio":
                  for (e = 0; e < lf.length; e++) D(lf[e], d);
                  break;
                case "source":
                  D("error", d);
                  break;
                case "img":
                case "image":
                case "link":
                  D(
                    "error",
                    d
                  );
                  D("load", d);
                  break;
                case "details":
                  D("toggle", d);
                  break;
                case "input":
                  Za(d, f);
                  D("invalid", d);
                  break;
                case "select":
                  d._wrapperState = { wasMultiple: !!f.multiple };
                  D("invalid", d);
                  break;
                case "textarea":
                  hb(d, f), D("invalid", d);
              }
              ub(c, f);
              e = null;
              for (var g in f) if (f.hasOwnProperty(g)) {
                var h = f[g];
                "children" === g ? "string" === typeof h ? d.textContent !== h && (true !== f.suppressHydrationWarning && Af(d.textContent, h, a), e = ["children", h]) : "number" === typeof h && d.textContent !== "" + h && (true !== f.suppressHydrationWarning && Af(
                  d.textContent,
                  h,
                  a
                ), e = ["children", "" + h]) : ea.hasOwnProperty(g) && null != h && "onScroll" === g && D("scroll", d);
              }
              switch (c) {
                case "input":
                  Va(d);
                  db(d, f, true);
                  break;
                case "textarea":
                  Va(d);
                  jb(d);
                  break;
                case "select":
                case "option":
                  break;
                default:
                  "function" === typeof f.onClick && (d.onclick = Bf);
              }
              d = e;
              b.updateQueue = d;
              null !== d && (b.flags |= 4);
            } else {
              g = 9 === e.nodeType ? e : e.ownerDocument;
              "http://www.w3.org/1999/xhtml" === a && (a = kb(c));
              "http://www.w3.org/1999/xhtml" === a ? "script" === c ? (a = g.createElement("div"), a.innerHTML = "<script><\/script>", a = a.removeChild(a.firstChild)) : "string" === typeof d.is ? a = g.createElement(c, { is: d.is }) : (a = g.createElement(c), "select" === c && (g = a, d.multiple ? g.multiple = true : d.size && (g.size = d.size))) : a = g.createElementNS(a, c);
              a[Of] = b;
              a[Pf] = d;
              zj(a, b, false, false);
              b.stateNode = a;
              a: {
                g = vb(c, d);
                switch (c) {
                  case "dialog":
                    D("cancel", a);
                    D("close", a);
                    e = d;
                    break;
                  case "iframe":
                  case "object":
                  case "embed":
                    D("load", a);
                    e = d;
                    break;
                  case "video":
                  case "audio":
                    for (e = 0; e < lf.length; e++) D(lf[e], a);
                    e = d;
                    break;
                  case "source":
                    D("error", a);
                    e = d;
                    break;
                  case "img":
                  case "image":
                  case "link":
                    D(
                      "error",
                      a
                    );
                    D("load", a);
                    e = d;
                    break;
                  case "details":
                    D("toggle", a);
                    e = d;
                    break;
                  case "input":
                    Za(a, d);
                    e = Ya(a, d);
                    D("invalid", a);
                    break;
                  case "option":
                    e = d;
                    break;
                  case "select":
                    a._wrapperState = { wasMultiple: !!d.multiple };
                    e = A({}, d, { value: void 0 });
                    D("invalid", a);
                    break;
                  case "textarea":
                    hb(a, d);
                    e = gb(a, d);
                    D("invalid", a);
                    break;
                  default:
                    e = d;
                }
                ub(c, e);
                h = e;
                for (f in h) if (h.hasOwnProperty(f)) {
                  var k = h[f];
                  "style" === f ? sb(a, k) : "dangerouslySetInnerHTML" === f ? (k = k ? k.__html : void 0, null != k && nb(a, k)) : "children" === f ? "string" === typeof k ? ("textarea" !== c || "" !== k) && ob(a, k) : "number" === typeof k && ob(a, "" + k) : "suppressContentEditableWarning" !== f && "suppressHydrationWarning" !== f && "autoFocus" !== f && (ea.hasOwnProperty(f) ? null != k && "onScroll" === f && D("scroll", a) : null != k && ta(a, f, k, g));
                }
                switch (c) {
                  case "input":
                    Va(a);
                    db(a, d, false);
                    break;
                  case "textarea":
                    Va(a);
                    jb(a);
                    break;
                  case "option":
                    null != d.value && a.setAttribute("value", "" + Sa(d.value));
                    break;
                  case "select":
                    a.multiple = !!d.multiple;
                    f = d.value;
                    null != f ? fb(a, !!d.multiple, f, false) : null != d.defaultValue && fb(
                      a,
                      !!d.multiple,
                      d.defaultValue,
                      true
                    );
                    break;
                  default:
                    "function" === typeof e.onClick && (a.onclick = Bf);
                }
                switch (c) {
                  case "button":
                  case "input":
                  case "select":
                  case "textarea":
                    d = !!d.autoFocus;
                    break a;
                  case "img":
                    d = true;
                    break a;
                  default:
                    d = false;
                }
              }
              d && (b.flags |= 4);
            }
            null !== b.ref && (b.flags |= 512, b.flags |= 2097152);
          }
          S(b);
          return null;
        case 6:
          if (a && null != b.stateNode) Cj(a, b, a.memoizedProps, d);
          else {
            if ("string" !== typeof d && null === b.stateNode) throw Error(p(166));
            c = xh(wh.current);
            xh(uh.current);
            if (Gg(b)) {
              d = b.stateNode;
              c = b.memoizedProps;
              d[Of] = b;
              if (f = d.nodeValue !== c) {
                if (a = xg, null !== a) switch (a.tag) {
                  case 3:
                    Af(d.nodeValue, c, 0 !== (a.mode & 1));
                    break;
                  case 5:
                    true !== a.memoizedProps.suppressHydrationWarning && Af(d.nodeValue, c, 0 !== (a.mode & 1));
                }
              }
              f && (b.flags |= 4);
            } else d = (9 === c.nodeType ? c : c.ownerDocument).createTextNode(d), d[Of] = b, b.stateNode = d;
          }
          S(b);
          return null;
        case 13:
          E(L);
          d = b.memoizedState;
          if (null === a || null !== a.memoizedState && null !== a.memoizedState.dehydrated) {
            if (I && null !== yg && 0 !== (b.mode & 1) && 0 === (b.flags & 128)) Hg(), Ig(), b.flags |= 98560, f = false;
            else if (f = Gg(b), null !== d && null !== d.dehydrated) {
              if (null === a) {
                if (!f) throw Error(p(318));
                f = b.memoizedState;
                f = null !== f ? f.dehydrated : null;
                if (!f) throw Error(p(317));
                f[Of] = b;
              } else Ig(), 0 === (b.flags & 128) && (b.memoizedState = null), b.flags |= 4;
              S(b);
              f = false;
            } else null !== zg && (Fj(zg), zg = null), f = true;
            if (!f) return b.flags & 65536 ? b : null;
          }
          if (0 !== (b.flags & 128)) return b.lanes = c, b;
          d = null !== d;
          d !== (null !== a && null !== a.memoizedState) && d && (b.child.flags |= 8192, 0 !== (b.mode & 1) && (null === a || 0 !== (L.current & 1) ? 0 === T && (T = 3) : tj()));
          null !== b.updateQueue && (b.flags |= 4);
          S(b);
          return null;
        case 4:
          return zh(), Aj(a, b), null === a && sf(b.stateNode.containerInfo), S(b), null;
        case 10:
          return ah(b.type._context), S(b), null;
        case 17:
          return Zf(b.type) && $f(), S(b), null;
        case 19:
          E(L);
          f = b.memoizedState;
          if (null === f) return S(b), null;
          d = 0 !== (b.flags & 128);
          g = f.rendering;
          if (null === g) if (d) Dj(f, false);
          else {
            if (0 !== T || null !== a && 0 !== (a.flags & 128)) for (a = b.child; null !== a; ) {
              g = Ch(a);
              if (null !== g) {
                b.flags |= 128;
                Dj(f, false);
                d = g.updateQueue;
                null !== d && (b.updateQueue = d, b.flags |= 4);
                b.subtreeFlags = 0;
                d = c;
                for (c = b.child; null !== c; ) f = c, a = d, f.flags &= 14680066, g = f.alternate, null === g ? (f.childLanes = 0, f.lanes = a, f.child = null, f.subtreeFlags = 0, f.memoizedProps = null, f.memoizedState = null, f.updateQueue = null, f.dependencies = null, f.stateNode = null) : (f.childLanes = g.childLanes, f.lanes = g.lanes, f.child = g.child, f.subtreeFlags = 0, f.deletions = null, f.memoizedProps = g.memoizedProps, f.memoizedState = g.memoizedState, f.updateQueue = g.updateQueue, f.type = g.type, a = g.dependencies, f.dependencies = null === a ? null : { lanes: a.lanes, firstContext: a.firstContext }), c = c.sibling;
                G(L, L.current & 1 | 2);
                return b.child;
              }
              a = a.sibling;
            }
            null !== f.tail && B() > Gj && (b.flags |= 128, d = true, Dj(f, false), b.lanes = 4194304);
          }
          else {
            if (!d) if (a = Ch(g), null !== a) {
              if (b.flags |= 128, d = true, c = a.updateQueue, null !== c && (b.updateQueue = c, b.flags |= 4), Dj(f, true), null === f.tail && "hidden" === f.tailMode && !g.alternate && !I) return S(b), null;
            } else 2 * B() - f.renderingStartTime > Gj && 1073741824 !== c && (b.flags |= 128, d = true, Dj(f, false), b.lanes = 4194304);
            f.isBackwards ? (g.sibling = b.child, b.child = g) : (c = f.last, null !== c ? c.sibling = g : b.child = g, f.last = g);
          }
          if (null !== f.tail) return b = f.tail, f.rendering = b, f.tail = b.sibling, f.renderingStartTime = B(), b.sibling = null, c = L.current, G(L, d ? c & 1 | 2 : c & 1), b;
          S(b);
          return null;
        case 22:
        case 23:
          return Hj(), d = null !== b.memoizedState, null !== a && null !== a.memoizedState !== d && (b.flags |= 8192), d && 0 !== (b.mode & 1) ? 0 !== (fj & 1073741824) && (S(b), b.subtreeFlags & 6 && (b.flags |= 8192)) : S(b), null;
        case 24:
          return null;
        case 25:
          return null;
      }
      throw Error(p(156, b.tag));
    }
    function Ij(a, b) {
      wg(b);
      switch (b.tag) {
        case 1:
          return Zf(b.type) && $f(), a = b.flags, a & 65536 ? (b.flags = a & -65537 | 128, b) : null;
        case 3:
          return zh(), E(Wf), E(H), Eh(), a = b.flags, 0 !== (a & 65536) && 0 === (a & 128) ? (b.flags = a & -65537 | 128, b) : null;
        case 5:
          return Bh(b), null;
        case 13:
          E(L);
          a = b.memoizedState;
          if (null !== a && null !== a.dehydrated) {
            if (null === b.alternate) throw Error(p(340));
            Ig();
          }
          a = b.flags;
          return a & 65536 ? (b.flags = a & -65537 | 128, b) : null;
        case 19:
          return E(L), null;
        case 4:
          return zh(), null;
        case 10:
          return ah(b.type._context), null;
        case 22:
        case 23:
          return Hj(), null;
        case 24:
          return null;
        default:
          return null;
      }
    }
    var Jj = false, U = false, Kj = "function" === typeof WeakSet ? WeakSet : Set, V = null;
    function Lj(a, b) {
      var c = a.ref;
      if (null !== c) if ("function" === typeof c) try {
        c(null);
      } catch (d) {
        W(a, b, d);
      }
      else c.current = null;
    }
    function Mj(a, b, c) {
      try {
        c();
      } catch (d) {
        W(a, b, d);
      }
    }
    var Nj = false;
    function Oj(a, b) {
      Cf = dd;
      a = Me();
      if (Ne(a)) {
        if ("selectionStart" in a) var c = { start: a.selectionStart, end: a.selectionEnd };
        else a: {
          c = (c = a.ownerDocument) && c.defaultView || window;
          var d = c.getSelection && c.getSelection();
          if (d && 0 !== d.rangeCount) {
            c = d.anchorNode;
            var e = d.anchorOffset, f = d.focusNode;
            d = d.focusOffset;
            try {
              c.nodeType, f.nodeType;
            } catch (F) {
              c = null;
              break a;
            }
            var g = 0, h = -1, k = -1, l = 0, m = 0, q = a, r2 = null;
            b: for (; ; ) {
              for (var y; ; ) {
                q !== c || 0 !== e && 3 !== q.nodeType || (h = g + e);
                q !== f || 0 !== d && 3 !== q.nodeType || (k = g + d);
                3 === q.nodeType && (g += q.nodeValue.length);
                if (null === (y = q.firstChild)) break;
                r2 = q;
                q = y;
              }
              for (; ; ) {
                if (q === a) break b;
                r2 === c && ++l === e && (h = g);
                r2 === f && ++m === d && (k = g);
                if (null !== (y = q.nextSibling)) break;
                q = r2;
                r2 = q.parentNode;
              }
              q = y;
            }
            c = -1 === h || -1 === k ? null : { start: h, end: k };
          } else c = null;
        }
        c = c || { start: 0, end: 0 };
      } else c = null;
      Df = { focusedElem: a, selectionRange: c };
      dd = false;
      for (V = b; null !== V; ) if (b = V, a = b.child, 0 !== (b.subtreeFlags & 1028) && null !== a) a.return = b, V = a;
      else for (; null !== V; ) {
        b = V;
        try {
          var n = b.alternate;
          if (0 !== (b.flags & 1024)) switch (b.tag) {
            case 0:
            case 11:
            case 15:
              break;
            case 1:
              if (null !== n) {
                var t = n.memoizedProps, J = n.memoizedState, x = b.stateNode, w = x.getSnapshotBeforeUpdate(b.elementType === b.type ? t : Ci(b.type, t), J);
                x.__reactInternalSnapshotBeforeUpdate = w;
              }
              break;
            case 3:
              var u = b.stateNode.containerInfo;
              1 === u.nodeType ? u.textContent = "" : 9 === u.nodeType && u.documentElement && u.removeChild(u.documentElement);
              break;
            case 5:
            case 6:
            case 4:
            case 17:
              break;
            default:
              throw Error(p(163));
          }
        } catch (F) {
          W(b, b.return, F);
        }
        a = b.sibling;
        if (null !== a) {
          a.return = b.return;
          V = a;
          break;
        }
        V = b.return;
      }
      n = Nj;
      Nj = false;
      return n;
    }
    function Pj(a, b, c) {
      var d = b.updateQueue;
      d = null !== d ? d.lastEffect : null;
      if (null !== d) {
        var e = d = d.next;
        do {
          if ((e.tag & a) === a) {
            var f = e.destroy;
            e.destroy = void 0;
            void 0 !== f && Mj(b, c, f);
          }
          e = e.next;
        } while (e !== d);
      }
    }
    function Qj(a, b) {
      b = b.updateQueue;
      b = null !== b ? b.lastEffect : null;
      if (null !== b) {
        var c = b = b.next;
        do {
          if ((c.tag & a) === a) {
            var d = c.create;
            c.destroy = d();
          }
          c = c.next;
        } while (c !== b);
      }
    }
    function Rj(a) {
      var b = a.ref;
      if (null !== b) {
        var c = a.stateNode;
        switch (a.tag) {
          case 5:
            a = c;
            break;
          default:
            a = c;
        }
        "function" === typeof b ? b(a) : b.current = a;
      }
    }
    function Sj(a) {
      var b = a.alternate;
      null !== b && (a.alternate = null, Sj(b));
      a.child = null;
      a.deletions = null;
      a.sibling = null;
      5 === a.tag && (b = a.stateNode, null !== b && (delete b[Of], delete b[Pf], delete b[of], delete b[Qf], delete b[Rf]));
      a.stateNode = null;
      a.return = null;
      a.dependencies = null;
      a.memoizedProps = null;
      a.memoizedState = null;
      a.pendingProps = null;
      a.stateNode = null;
      a.updateQueue = null;
    }
    function Tj(a) {
      return 5 === a.tag || 3 === a.tag || 4 === a.tag;
    }
    function Uj(a) {
      a: for (; ; ) {
        for (; null === a.sibling; ) {
          if (null === a.return || Tj(a.return)) return null;
          a = a.return;
        }
        a.sibling.return = a.return;
        for (a = a.sibling; 5 !== a.tag && 6 !== a.tag && 18 !== a.tag; ) {
          if (a.flags & 2) continue a;
          if (null === a.child || 4 === a.tag) continue a;
          else a.child.return = a, a = a.child;
        }
        if (!(a.flags & 2)) return a.stateNode;
      }
    }
    function Vj(a, b, c) {
      var d = a.tag;
      if (5 === d || 6 === d) a = a.stateNode, b ? 8 === c.nodeType ? c.parentNode.insertBefore(a, b) : c.insertBefore(a, b) : (8 === c.nodeType ? (b = c.parentNode, b.insertBefore(a, c)) : (b = c, b.appendChild(a)), c = c._reactRootContainer, null !== c && void 0 !== c || null !== b.onclick || (b.onclick = Bf));
      else if (4 !== d && (a = a.child, null !== a)) for (Vj(a, b, c), a = a.sibling; null !== a; ) Vj(a, b, c), a = a.sibling;
    }
    function Wj(a, b, c) {
      var d = a.tag;
      if (5 === d || 6 === d) a = a.stateNode, b ? c.insertBefore(a, b) : c.appendChild(a);
      else if (4 !== d && (a = a.child, null !== a)) for (Wj(a, b, c), a = a.sibling; null !== a; ) Wj(a, b, c), a = a.sibling;
    }
    var X2 = null, Xj = false;
    function Yj(a, b, c) {
      for (c = c.child; null !== c; ) Zj(a, b, c), c = c.sibling;
    }
    function Zj(a, b, c) {
      if (lc && "function" === typeof lc.onCommitFiberUnmount) try {
        lc.onCommitFiberUnmount(kc, c);
      } catch (h) {
      }
      switch (c.tag) {
        case 5:
          U || Lj(c, b);
        case 6:
          var d = X2, e = Xj;
          X2 = null;
          Yj(a, b, c);
          X2 = d;
          Xj = e;
          null !== X2 && (Xj ? (a = X2, c = c.stateNode, 8 === a.nodeType ? a.parentNode.removeChild(c) : a.removeChild(c)) : X2.removeChild(c.stateNode));
          break;
        case 18:
          null !== X2 && (Xj ? (a = X2, c = c.stateNode, 8 === a.nodeType ? Kf(a.parentNode, c) : 1 === a.nodeType && Kf(a, c), bd(a)) : Kf(X2, c.stateNode));
          break;
        case 4:
          d = X2;
          e = Xj;
          X2 = c.stateNode.containerInfo;
          Xj = true;
          Yj(a, b, c);
          X2 = d;
          Xj = e;
          break;
        case 0:
        case 11:
        case 14:
        case 15:
          if (!U && (d = c.updateQueue, null !== d && (d = d.lastEffect, null !== d))) {
            e = d = d.next;
            do {
              var f = e, g = f.destroy;
              f = f.tag;
              void 0 !== g && (0 !== (f & 2) ? Mj(c, b, g) : 0 !== (f & 4) && Mj(c, b, g));
              e = e.next;
            } while (e !== d);
          }
          Yj(a, b, c);
          break;
        case 1:
          if (!U && (Lj(c, b), d = c.stateNode, "function" === typeof d.componentWillUnmount)) try {
            d.props = c.memoizedProps, d.state = c.memoizedState, d.componentWillUnmount();
          } catch (h) {
            W(c, b, h);
          }
          Yj(a, b, c);
          break;
        case 21:
          Yj(a, b, c);
          break;
        case 22:
          c.mode & 1 ? (U = (d = U) || null !== c.memoizedState, Yj(a, b, c), U = d) : Yj(a, b, c);
          break;
        default:
          Yj(a, b, c);
      }
    }
    function ak(a) {
      var b = a.updateQueue;
      if (null !== b) {
        a.updateQueue = null;
        var c = a.stateNode;
        null === c && (c = a.stateNode = new Kj());
        b.forEach(function(b2) {
          var d = bk.bind(null, a, b2);
          c.has(b2) || (c.add(b2), b2.then(d, d));
        });
      }
    }
    function ck(a, b) {
      var c = b.deletions;
      if (null !== c) for (var d = 0; d < c.length; d++) {
        var e = c[d];
        try {
          var f = a, g = b, h = g;
          a: for (; null !== h; ) {
            switch (h.tag) {
              case 5:
                X2 = h.stateNode;
                Xj = false;
                break a;
              case 3:
                X2 = h.stateNode.containerInfo;
                Xj = true;
                break a;
              case 4:
                X2 = h.stateNode.containerInfo;
                Xj = true;
                break a;
            }
            h = h.return;
          }
          if (null === X2) throw Error(p(160));
          Zj(f, g, e);
          X2 = null;
          Xj = false;
          var k = e.alternate;
          null !== k && (k.return = null);
          e.return = null;
        } catch (l) {
          W(e, b, l);
        }
      }
      if (b.subtreeFlags & 12854) for (b = b.child; null !== b; ) dk(b, a), b = b.sibling;
    }
    function dk(a, b) {
      var c = a.alternate, d = a.flags;
      switch (a.tag) {
        case 0:
        case 11:
        case 14:
        case 15:
          ck(b, a);
          ek(a);
          if (d & 4) {
            try {
              Pj(3, a, a.return), Qj(3, a);
            } catch (t) {
              W(a, a.return, t);
            }
            try {
              Pj(5, a, a.return);
            } catch (t) {
              W(a, a.return, t);
            }
          }
          break;
        case 1:
          ck(b, a);
          ek(a);
          d & 512 && null !== c && Lj(c, c.return);
          break;
        case 5:
          ck(b, a);
          ek(a);
          d & 512 && null !== c && Lj(c, c.return);
          if (a.flags & 32) {
            var e = a.stateNode;
            try {
              ob(e, "");
            } catch (t) {
              W(a, a.return, t);
            }
          }
          if (d & 4 && (e = a.stateNode, null != e)) {
            var f = a.memoizedProps, g = null !== c ? c.memoizedProps : f, h = a.type, k = a.updateQueue;
            a.updateQueue = null;
            if (null !== k) try {
              "input" === h && "radio" === f.type && null != f.name && ab(e, f);
              vb(h, g);
              var l = vb(h, f);
              for (g = 0; g < k.length; g += 2) {
                var m = k[g], q = k[g + 1];
                "style" === m ? sb(e, q) : "dangerouslySetInnerHTML" === m ? nb(e, q) : "children" === m ? ob(e, q) : ta(e, m, q, l);
              }
              switch (h) {
                case "input":
                  bb(e, f);
                  break;
                case "textarea":
                  ib(e, f);
                  break;
                case "select":
                  var r2 = e._wrapperState.wasMultiple;
                  e._wrapperState.wasMultiple = !!f.multiple;
                  var y = f.value;
                  null != y ? fb(e, !!f.multiple, y, false) : r2 !== !!f.multiple && (null != f.defaultValue ? fb(
                    e,
                    !!f.multiple,
                    f.defaultValue,
                    true
                  ) : fb(e, !!f.multiple, f.multiple ? [] : "", false));
              }
              e[Pf] = f;
            } catch (t) {
              W(a, a.return, t);
            }
          }
          break;
        case 6:
          ck(b, a);
          ek(a);
          if (d & 4) {
            if (null === a.stateNode) throw Error(p(162));
            e = a.stateNode;
            f = a.memoizedProps;
            try {
              e.nodeValue = f;
            } catch (t) {
              W(a, a.return, t);
            }
          }
          break;
        case 3:
          ck(b, a);
          ek(a);
          if (d & 4 && null !== c && c.memoizedState.isDehydrated) try {
            bd(b.containerInfo);
          } catch (t) {
            W(a, a.return, t);
          }
          break;
        case 4:
          ck(b, a);
          ek(a);
          break;
        case 13:
          ck(b, a);
          ek(a);
          e = a.child;
          e.flags & 8192 && (f = null !== e.memoizedState, e.stateNode.isHidden = f, !f || null !== e.alternate && null !== e.alternate.memoizedState || (fk = B()));
          d & 4 && ak(a);
          break;
        case 22:
          m = null !== c && null !== c.memoizedState;
          a.mode & 1 ? (U = (l = U) || m, ck(b, a), U = l) : ck(b, a);
          ek(a);
          if (d & 8192) {
            l = null !== a.memoizedState;
            if ((a.stateNode.isHidden = l) && !m && 0 !== (a.mode & 1)) for (V = a, m = a.child; null !== m; ) {
              for (q = V = m; null !== V; ) {
                r2 = V;
                y = r2.child;
                switch (r2.tag) {
                  case 0:
                  case 11:
                  case 14:
                  case 15:
                    Pj(4, r2, r2.return);
                    break;
                  case 1:
                    Lj(r2, r2.return);
                    var n = r2.stateNode;
                    if ("function" === typeof n.componentWillUnmount) {
                      d = r2;
                      c = r2.return;
                      try {
                        b = d, n.props = b.memoizedProps, n.state = b.memoizedState, n.componentWillUnmount();
                      } catch (t) {
                        W(d, c, t);
                      }
                    }
                    break;
                  case 5:
                    Lj(r2, r2.return);
                    break;
                  case 22:
                    if (null !== r2.memoizedState) {
                      gk(q);
                      continue;
                    }
                }
                null !== y ? (y.return = r2, V = y) : gk(q);
              }
              m = m.sibling;
            }
            a: for (m = null, q = a; ; ) {
              if (5 === q.tag) {
                if (null === m) {
                  m = q;
                  try {
                    e = q.stateNode, l ? (f = e.style, "function" === typeof f.setProperty ? f.setProperty("display", "none", "important") : f.display = "none") : (h = q.stateNode, k = q.memoizedProps.style, g = void 0 !== k && null !== k && k.hasOwnProperty("display") ? k.display : null, h.style.display = rb("display", g));
                  } catch (t) {
                    W(a, a.return, t);
                  }
                }
              } else if (6 === q.tag) {
                if (null === m) try {
                  q.stateNode.nodeValue = l ? "" : q.memoizedProps;
                } catch (t) {
                  W(a, a.return, t);
                }
              } else if ((22 !== q.tag && 23 !== q.tag || null === q.memoizedState || q === a) && null !== q.child) {
                q.child.return = q;
                q = q.child;
                continue;
              }
              if (q === a) break a;
              for (; null === q.sibling; ) {
                if (null === q.return || q.return === a) break a;
                m === q && (m = null);
                q = q.return;
              }
              m === q && (m = null);
              q.sibling.return = q.return;
              q = q.sibling;
            }
          }
          break;
        case 19:
          ck(b, a);
          ek(a);
          d & 4 && ak(a);
          break;
        case 21:
          break;
        default:
          ck(
            b,
            a
          ), ek(a);
      }
    }
    function ek(a) {
      var b = a.flags;
      if (b & 2) {
        try {
          a: {
            for (var c = a.return; null !== c; ) {
              if (Tj(c)) {
                var d = c;
                break a;
              }
              c = c.return;
            }
            throw Error(p(160));
          }
          switch (d.tag) {
            case 5:
              var e = d.stateNode;
              d.flags & 32 && (ob(e, ""), d.flags &= -33);
              var f = Uj(a);
              Wj(a, f, e);
              break;
            case 3:
            case 4:
              var g = d.stateNode.containerInfo, h = Uj(a);
              Vj(a, h, g);
              break;
            default:
              throw Error(p(161));
          }
        } catch (k) {
          W(a, a.return, k);
        }
        a.flags &= -3;
      }
      b & 4096 && (a.flags &= -4097);
    }
    function hk(a, b, c) {
      V = a;
      ik(a);
    }
    function ik(a, b, c) {
      for (var d = 0 !== (a.mode & 1); null !== V; ) {
        var e = V, f = e.child;
        if (22 === e.tag && d) {
          var g = null !== e.memoizedState || Jj;
          if (!g) {
            var h = e.alternate, k = null !== h && null !== h.memoizedState || U;
            h = Jj;
            var l = U;
            Jj = g;
            if ((U = k) && !l) for (V = e; null !== V; ) g = V, k = g.child, 22 === g.tag && null !== g.memoizedState ? jk(e) : null !== k ? (k.return = g, V = k) : jk(e);
            for (; null !== f; ) V = f, ik(f), f = f.sibling;
            V = e;
            Jj = h;
            U = l;
          }
          kk(a);
        } else 0 !== (e.subtreeFlags & 8772) && null !== f ? (f.return = e, V = f) : kk(a);
      }
    }
    function kk(a) {
      for (; null !== V; ) {
        var b = V;
        if (0 !== (b.flags & 8772)) {
          var c = b.alternate;
          try {
            if (0 !== (b.flags & 8772)) switch (b.tag) {
              case 0:
              case 11:
              case 15:
                U || Qj(5, b);
                break;
              case 1:
                var d = b.stateNode;
                if (b.flags & 4 && !U) if (null === c) d.componentDidMount();
                else {
                  var e = b.elementType === b.type ? c.memoizedProps : Ci(b.type, c.memoizedProps);
                  d.componentDidUpdate(e, c.memoizedState, d.__reactInternalSnapshotBeforeUpdate);
                }
                var f = b.updateQueue;
                null !== f && sh(b, f, d);
                break;
              case 3:
                var g = b.updateQueue;
                if (null !== g) {
                  c = null;
                  if (null !== b.child) switch (b.child.tag) {
                    case 5:
                      c = b.child.stateNode;
                      break;
                    case 1:
                      c = b.child.stateNode;
                  }
                  sh(b, g, c);
                }
                break;
              case 5:
                var h = b.stateNode;
                if (null === c && b.flags & 4) {
                  c = h;
                  var k = b.memoizedProps;
                  switch (b.type) {
                    case "button":
                    case "input":
                    case "select":
                    case "textarea":
                      k.autoFocus && c.focus();
                      break;
                    case "img":
                      k.src && (c.src = k.src);
                  }
                }
                break;
              case 6:
                break;
              case 4:
                break;
              case 12:
                break;
              case 13:
                if (null === b.memoizedState) {
                  var l = b.alternate;
                  if (null !== l) {
                    var m = l.memoizedState;
                    if (null !== m) {
                      var q = m.dehydrated;
                      null !== q && bd(q);
                    }
                  }
                }
                break;
              case 19:
              case 17:
              case 21:
              case 22:
              case 23:
              case 25:
                break;
              default:
                throw Error(p(163));
            }
            U || b.flags & 512 && Rj(b);
          } catch (r2) {
            W(b, b.return, r2);
          }
        }
        if (b === a) {
          V = null;
          break;
        }
        c = b.sibling;
        if (null !== c) {
          c.return = b.return;
          V = c;
          break;
        }
        V = b.return;
      }
    }
    function gk(a) {
      for (; null !== V; ) {
        var b = V;
        if (b === a) {
          V = null;
          break;
        }
        var c = b.sibling;
        if (null !== c) {
          c.return = b.return;
          V = c;
          break;
        }
        V = b.return;
      }
    }
    function jk(a) {
      for (; null !== V; ) {
        var b = V;
        try {
          switch (b.tag) {
            case 0:
            case 11:
            case 15:
              var c = b.return;
              try {
                Qj(4, b);
              } catch (k) {
                W(b, c, k);
              }
              break;
            case 1:
              var d = b.stateNode;
              if ("function" === typeof d.componentDidMount) {
                var e = b.return;
                try {
                  d.componentDidMount();
                } catch (k) {
                  W(b, e, k);
                }
              }
              var f = b.return;
              try {
                Rj(b);
              } catch (k) {
                W(b, f, k);
              }
              break;
            case 5:
              var g = b.return;
              try {
                Rj(b);
              } catch (k) {
                W(b, g, k);
              }
          }
        } catch (k) {
          W(b, b.return, k);
        }
        if (b === a) {
          V = null;
          break;
        }
        var h = b.sibling;
        if (null !== h) {
          h.return = b.return;
          V = h;
          break;
        }
        V = b.return;
      }
    }
    var lk = Math.ceil, mk = ua.ReactCurrentDispatcher, nk = ua.ReactCurrentOwner, ok2 = ua.ReactCurrentBatchConfig, K = 0, Q = null, Y = null, Z = 0, fj = 0, ej = Uf(0), T = 0, pk = null, rh = 0, qk = 0, rk = 0, sk = null, tk = null, fk = 0, Gj = Infinity, uk = null, Oi = false, Pi = null, Ri = null, vk = false, wk = null, xk = 0, yk = 0, zk = null, Ak = -1, Bk = 0;
    function R() {
      return 0 !== (K & 6) ? B() : -1 !== Ak ? Ak : Ak = B();
    }
    function yi(a) {
      if (0 === (a.mode & 1)) return 1;
      if (0 !== (K & 2) && 0 !== Z) return Z & -Z;
      if (null !== Kg.transition) return 0 === Bk && (Bk = yc()), Bk;
      a = C;
      if (0 !== a) return a;
      a = window.event;
      a = void 0 === a ? 16 : jd(a.type);
      return a;
    }
    function gi(a, b, c, d) {
      if (50 < yk) throw yk = 0, zk = null, Error(p(185));
      Ac(a, c, d);
      if (0 === (K & 2) || a !== Q) a === Q && (0 === (K & 2) && (qk |= c), 4 === T && Ck(a, Z)), Dk(a, d), 1 === c && 0 === K && 0 === (b.mode & 1) && (Gj = B() + 500, fg && jg());
    }
    function Dk(a, b) {
      var c = a.callbackNode;
      wc(a, b);
      var d = uc(a, a === Q ? Z : 0);
      if (0 === d) null !== c && bc(c), a.callbackNode = null, a.callbackPriority = 0;
      else if (b = d & -d, a.callbackPriority !== b) {
        null != c && bc(c);
        if (1 === b) 0 === a.tag ? ig(Ek.bind(null, a)) : hg(Ek.bind(null, a)), Jf(function() {
          0 === (K & 6) && jg();
        }), c = null;
        else {
          switch (Dc(d)) {
            case 1:
              c = fc;
              break;
            case 4:
              c = gc;
              break;
            case 16:
              c = hc;
              break;
            case 536870912:
              c = jc;
              break;
            default:
              c = hc;
          }
          c = Fk(c, Gk.bind(null, a));
        }
        a.callbackPriority = b;
        a.callbackNode = c;
      }
    }
    function Gk(a, b) {
      Ak = -1;
      Bk = 0;
      if (0 !== (K & 6)) throw Error(p(327));
      var c = a.callbackNode;
      if (Hk() && a.callbackNode !== c) return null;
      var d = uc(a, a === Q ? Z : 0);
      if (0 === d) return null;
      if (0 !== (d & 30) || 0 !== (d & a.expiredLanes) || b) b = Ik(a, d);
      else {
        b = d;
        var e = K;
        K |= 2;
        var f = Jk();
        if (Q !== a || Z !== b) uk = null, Gj = B() + 500, Kk(a, b);
        do
          try {
            Lk();
            break;
          } catch (h) {
            Mk(a, h);
          }
        while (1);
        $g();
        mk.current = f;
        K = e;
        null !== Y ? b = 0 : (Q = null, Z = 0, b = T);
      }
      if (0 !== b) {
        2 === b && (e = xc(a), 0 !== e && (d = e, b = Nk(a, e)));
        if (1 === b) throw c = pk, Kk(a, 0), Ck(a, d), Dk(a, B()), c;
        if (6 === b) Ck(a, d);
        else {
          e = a.current.alternate;
          if (0 === (d & 30) && !Ok(e) && (b = Ik(a, d), 2 === b && (f = xc(a), 0 !== f && (d = f, b = Nk(a, f))), 1 === b)) throw c = pk, Kk(a, 0), Ck(a, d), Dk(a, B()), c;
          a.finishedWork = e;
          a.finishedLanes = d;
          switch (b) {
            case 0:
            case 1:
              throw Error(p(345));
            case 2:
              Pk(a, tk, uk);
              break;
            case 3:
              Ck(a, d);
              if ((d & 130023424) === d && (b = fk + 500 - B(), 10 < b)) {
                if (0 !== uc(a, 0)) break;
                e = a.suspendedLanes;
                if ((e & d) !== d) {
                  R();
                  a.pingedLanes |= a.suspendedLanes & e;
                  break;
                }
                a.timeoutHandle = Ff(Pk.bind(null, a, tk, uk), b);
                break;
              }
              Pk(a, tk, uk);
              break;
            case 4:
              Ck(a, d);
              if ((d & 4194240) === d) break;
              b = a.eventTimes;
              for (e = -1; 0 < d; ) {
                var g = 31 - oc(d);
                f = 1 << g;
                g = b[g];
                g > e && (e = g);
                d &= ~f;
              }
              d = e;
              d = B() - d;
              d = (120 > d ? 120 : 480 > d ? 480 : 1080 > d ? 1080 : 1920 > d ? 1920 : 3e3 > d ? 3e3 : 4320 > d ? 4320 : 1960 * lk(d / 1960)) - d;
              if (10 < d) {
                a.timeoutHandle = Ff(Pk.bind(null, a, tk, uk), d);
                break;
              }
              Pk(a, tk, uk);
              break;
            case 5:
              Pk(a, tk, uk);
              break;
            default:
              throw Error(p(329));
          }
        }
      }
      Dk(a, B());
      return a.callbackNode === c ? Gk.bind(null, a) : null;
    }
    function Nk(a, b) {
      var c = sk;
      a.current.memoizedState.isDehydrated && (Kk(a, b).flags |= 256);
      a = Ik(a, b);
      2 !== a && (b = tk, tk = c, null !== b && Fj(b));
      return a;
    }
    function Fj(a) {
      null === tk ? tk = a : tk.push.apply(tk, a);
    }
    function Ok(a) {
      for (var b = a; ; ) {
        if (b.flags & 16384) {
          var c = b.updateQueue;
          if (null !== c && (c = c.stores, null !== c)) for (var d = 0; d < c.length; d++) {
            var e = c[d], f = e.getSnapshot;
            e = e.value;
            try {
              if (!He(f(), e)) return false;
            } catch (g) {
              return false;
            }
          }
        }
        c = b.child;
        if (b.subtreeFlags & 16384 && null !== c) c.return = b, b = c;
        else {
          if (b === a) break;
          for (; null === b.sibling; ) {
            if (null === b.return || b.return === a) return true;
            b = b.return;
          }
          b.sibling.return = b.return;
          b = b.sibling;
        }
      }
      return true;
    }
    function Ck(a, b) {
      b &= ~rk;
      b &= ~qk;
      a.suspendedLanes |= b;
      a.pingedLanes &= ~b;
      for (a = a.expirationTimes; 0 < b; ) {
        var c = 31 - oc(b), d = 1 << c;
        a[c] = -1;
        b &= ~d;
      }
    }
    function Ek(a) {
      if (0 !== (K & 6)) throw Error(p(327));
      Hk();
      var b = uc(a, 0);
      if (0 === (b & 1)) return Dk(a, B()), null;
      var c = Ik(a, b);
      if (0 !== a.tag && 2 === c) {
        var d = xc(a);
        0 !== d && (b = d, c = Nk(a, d));
      }
      if (1 === c) throw c = pk, Kk(a, 0), Ck(a, b), Dk(a, B()), c;
      if (6 === c) throw Error(p(345));
      a.finishedWork = a.current.alternate;
      a.finishedLanes = b;
      Pk(a, tk, uk);
      Dk(a, B());
      return null;
    }
    function Qk(a, b) {
      var c = K;
      K |= 1;
      try {
        return a(b);
      } finally {
        K = c, 0 === K && (Gj = B() + 500, fg && jg());
      }
    }
    function Rk(a) {
      null !== wk && 0 === wk.tag && 0 === (K & 6) && Hk();
      var b = K;
      K |= 1;
      var c = ok2.transition, d = C;
      try {
        if (ok2.transition = null, C = 1, a) return a();
      } finally {
        C = d, ok2.transition = c, K = b, 0 === (K & 6) && jg();
      }
    }
    function Hj() {
      fj = ej.current;
      E(ej);
    }
    function Kk(a, b) {
      a.finishedWork = null;
      a.finishedLanes = 0;
      var c = a.timeoutHandle;
      -1 !== c && (a.timeoutHandle = -1, Gf(c));
      if (null !== Y) for (c = Y.return; null !== c; ) {
        var d = c;
        wg(d);
        switch (d.tag) {
          case 1:
            d = d.type.childContextTypes;
            null !== d && void 0 !== d && $f();
            break;
          case 3:
            zh();
            E(Wf);
            E(H);
            Eh();
            break;
          case 5:
            Bh(d);
            break;
          case 4:
            zh();
            break;
          case 13:
            E(L);
            break;
          case 19:
            E(L);
            break;
          case 10:
            ah(d.type._context);
            break;
          case 22:
          case 23:
            Hj();
        }
        c = c.return;
      }
      Q = a;
      Y = a = Pg(a.current, null);
      Z = fj = b;
      T = 0;
      pk = null;
      rk = qk = rh = 0;
      tk = sk = null;
      if (null !== fh) {
        for (b = 0; b < fh.length; b++) if (c = fh[b], d = c.interleaved, null !== d) {
          c.interleaved = null;
          var e = d.next, f = c.pending;
          if (null !== f) {
            var g = f.next;
            f.next = e;
            d.next = g;
          }
          c.pending = d;
        }
        fh = null;
      }
      return a;
    }
    function Mk(a, b) {
      do {
        var c = Y;
        try {
          $g();
          Fh.current = Rh;
          if (Ih) {
            for (var d = M.memoizedState; null !== d; ) {
              var e = d.queue;
              null !== e && (e.pending = null);
              d = d.next;
            }
            Ih = false;
          }
          Hh = 0;
          O = N = M = null;
          Jh = false;
          Kh = 0;
          nk.current = null;
          if (null === c || null === c.return) {
            T = 1;
            pk = b;
            Y = null;
            break;
          }
          a: {
            var f = a, g = c.return, h = c, k = b;
            b = Z;
            h.flags |= 32768;
            if (null !== k && "object" === typeof k && "function" === typeof k.then) {
              var l = k, m = h, q = m.tag;
              if (0 === (m.mode & 1) && (0 === q || 11 === q || 15 === q)) {
                var r2 = m.alternate;
                r2 ? (m.updateQueue = r2.updateQueue, m.memoizedState = r2.memoizedState, m.lanes = r2.lanes) : (m.updateQueue = null, m.memoizedState = null);
              }
              var y = Ui(g);
              if (null !== y) {
                y.flags &= -257;
                Vi(y, g, h, f, b);
                y.mode & 1 && Si(f, l, b);
                b = y;
                k = l;
                var n = b.updateQueue;
                if (null === n) {
                  var t = /* @__PURE__ */ new Set();
                  t.add(k);
                  b.updateQueue = t;
                } else n.add(k);
                break a;
              } else {
                if (0 === (b & 1)) {
                  Si(f, l, b);
                  tj();
                  break a;
                }
                k = Error(p(426));
              }
            } else if (I && h.mode & 1) {
              var J = Ui(g);
              if (null !== J) {
                0 === (J.flags & 65536) && (J.flags |= 256);
                Vi(J, g, h, f, b);
                Jg(Ji(k, h));
                break a;
              }
            }
            f = k = Ji(k, h);
            4 !== T && (T = 2);
            null === sk ? sk = [f] : sk.push(f);
            f = g;
            do {
              switch (f.tag) {
                case 3:
                  f.flags |= 65536;
                  b &= -b;
                  f.lanes |= b;
                  var x = Ni(f, k, b);
                  ph(f, x);
                  break a;
                case 1:
                  h = k;
                  var w = f.type, u = f.stateNode;
                  if (0 === (f.flags & 128) && ("function" === typeof w.getDerivedStateFromError || null !== u && "function" === typeof u.componentDidCatch && (null === Ri || !Ri.has(u)))) {
                    f.flags |= 65536;
                    b &= -b;
                    f.lanes |= b;
                    var F = Qi(f, h, b);
                    ph(f, F);
                    break a;
                  }
              }
              f = f.return;
            } while (null !== f);
          }
          Sk(c);
        } catch (na) {
          b = na;
          Y === c && null !== c && (Y = c = c.return);
          continue;
        }
        break;
      } while (1);
    }
    function Jk() {
      var a = mk.current;
      mk.current = Rh;
      return null === a ? Rh : a;
    }
    function tj() {
      if (0 === T || 3 === T || 2 === T) T = 4;
      null === Q || 0 === (rh & 268435455) && 0 === (qk & 268435455) || Ck(Q, Z);
    }
    function Ik(a, b) {
      var c = K;
      K |= 2;
      var d = Jk();
      if (Q !== a || Z !== b) uk = null, Kk(a, b);
      do
        try {
          Tk();
          break;
        } catch (e) {
          Mk(a, e);
        }
      while (1);
      $g();
      K = c;
      mk.current = d;
      if (null !== Y) throw Error(p(261));
      Q = null;
      Z = 0;
      return T;
    }
    function Tk() {
      for (; null !== Y; ) Uk(Y);
    }
    function Lk() {
      for (; null !== Y && !cc(); ) Uk(Y);
    }
    function Uk(a) {
      var b = Vk(a.alternate, a, fj);
      a.memoizedProps = a.pendingProps;
      null === b ? Sk(a) : Y = b;
      nk.current = null;
    }
    function Sk(a) {
      var b = a;
      do {
        var c = b.alternate;
        a = b.return;
        if (0 === (b.flags & 32768)) {
          if (c = Ej(c, b, fj), null !== c) {
            Y = c;
            return;
          }
        } else {
          c = Ij(c, b);
          if (null !== c) {
            c.flags &= 32767;
            Y = c;
            return;
          }
          if (null !== a) a.flags |= 32768, a.subtreeFlags = 0, a.deletions = null;
          else {
            T = 6;
            Y = null;
            return;
          }
        }
        b = b.sibling;
        if (null !== b) {
          Y = b;
          return;
        }
        Y = b = a;
      } while (null !== b);
      0 === T && (T = 5);
    }
    function Pk(a, b, c) {
      var d = C, e = ok2.transition;
      try {
        ok2.transition = null, C = 1, Wk(a, b, c, d);
      } finally {
        ok2.transition = e, C = d;
      }
      return null;
    }
    function Wk(a, b, c, d) {
      do
        Hk();
      while (null !== wk);
      if (0 !== (K & 6)) throw Error(p(327));
      c = a.finishedWork;
      var e = a.finishedLanes;
      if (null === c) return null;
      a.finishedWork = null;
      a.finishedLanes = 0;
      if (c === a.current) throw Error(p(177));
      a.callbackNode = null;
      a.callbackPriority = 0;
      var f = c.lanes | c.childLanes;
      Bc(a, f);
      a === Q && (Y = Q = null, Z = 0);
      0 === (c.subtreeFlags & 2064) && 0 === (c.flags & 2064) || vk || (vk = true, Fk(hc, function() {
        Hk();
        return null;
      }));
      f = 0 !== (c.flags & 15990);
      if (0 !== (c.subtreeFlags & 15990) || f) {
        f = ok2.transition;
        ok2.transition = null;
        var g = C;
        C = 1;
        var h = K;
        K |= 4;
        nk.current = null;
        Oj(a, c);
        dk(c, a);
        Oe(Df);
        dd = !!Cf;
        Df = Cf = null;
        a.current = c;
        hk(c);
        dc();
        K = h;
        C = g;
        ok2.transition = f;
      } else a.current = c;
      vk && (vk = false, wk = a, xk = e);
      f = a.pendingLanes;
      0 === f && (Ri = null);
      mc(c.stateNode);
      Dk(a, B());
      if (null !== b) for (d = a.onRecoverableError, c = 0; c < b.length; c++) e = b[c], d(e.value, { componentStack: e.stack, digest: e.digest });
      if (Oi) throw Oi = false, a = Pi, Pi = null, a;
      0 !== (xk & 1) && 0 !== a.tag && Hk();
      f = a.pendingLanes;
      0 !== (f & 1) ? a === zk ? yk++ : (yk = 0, zk = a) : yk = 0;
      jg();
      return null;
    }
    function Hk() {
      if (null !== wk) {
        var a = Dc(xk), b = ok2.transition, c = C;
        try {
          ok2.transition = null;
          C = 16 > a ? 16 : a;
          if (null === wk) var d = false;
          else {
            a = wk;
            wk = null;
            xk = 0;
            if (0 !== (K & 6)) throw Error(p(331));
            var e = K;
            K |= 4;
            for (V = a.current; null !== V; ) {
              var f = V, g = f.child;
              if (0 !== (V.flags & 16)) {
                var h = f.deletions;
                if (null !== h) {
                  for (var k = 0; k < h.length; k++) {
                    var l = h[k];
                    for (V = l; null !== V; ) {
                      var m = V;
                      switch (m.tag) {
                        case 0:
                        case 11:
                        case 15:
                          Pj(8, m, f);
                      }
                      var q = m.child;
                      if (null !== q) q.return = m, V = q;
                      else for (; null !== V; ) {
                        m = V;
                        var r2 = m.sibling, y = m.return;
                        Sj(m);
                        if (m === l) {
                          V = null;
                          break;
                        }
                        if (null !== r2) {
                          r2.return = y;
                          V = r2;
                          break;
                        }
                        V = y;
                      }
                    }
                  }
                  var n = f.alternate;
                  if (null !== n) {
                    var t = n.child;
                    if (null !== t) {
                      n.child = null;
                      do {
                        var J = t.sibling;
                        t.sibling = null;
                        t = J;
                      } while (null !== t);
                    }
                  }
                  V = f;
                }
              }
              if (0 !== (f.subtreeFlags & 2064) && null !== g) g.return = f, V = g;
              else b: for (; null !== V; ) {
                f = V;
                if (0 !== (f.flags & 2048)) switch (f.tag) {
                  case 0:
                  case 11:
                  case 15:
                    Pj(9, f, f.return);
                }
                var x = f.sibling;
                if (null !== x) {
                  x.return = f.return;
                  V = x;
                  break b;
                }
                V = f.return;
              }
            }
            var w = a.current;
            for (V = w; null !== V; ) {
              g = V;
              var u = g.child;
              if (0 !== (g.subtreeFlags & 2064) && null !== u) u.return = g, V = u;
              else b: for (g = w; null !== V; ) {
                h = V;
                if (0 !== (h.flags & 2048)) try {
                  switch (h.tag) {
                    case 0:
                    case 11:
                    case 15:
                      Qj(9, h);
                  }
                } catch (na) {
                  W(h, h.return, na);
                }
                if (h === g) {
                  V = null;
                  break b;
                }
                var F = h.sibling;
                if (null !== F) {
                  F.return = h.return;
                  V = F;
                  break b;
                }
                V = h.return;
              }
            }
            K = e;
            jg();
            if (lc && "function" === typeof lc.onPostCommitFiberRoot) try {
              lc.onPostCommitFiberRoot(kc, a);
            } catch (na) {
            }
            d = true;
          }
          return d;
        } finally {
          C = c, ok2.transition = b;
        }
      }
      return false;
    }
    function Xk(a, b, c) {
      b = Ji(c, b);
      b = Ni(a, b, 1);
      a = nh(a, b, 1);
      b = R();
      null !== a && (Ac(a, 1, b), Dk(a, b));
    }
    function W(a, b, c) {
      if (3 === a.tag) Xk(a, a, c);
      else for (; null !== b; ) {
        if (3 === b.tag) {
          Xk(b, a, c);
          break;
        } else if (1 === b.tag) {
          var d = b.stateNode;
          if ("function" === typeof b.type.getDerivedStateFromError || "function" === typeof d.componentDidCatch && (null === Ri || !Ri.has(d))) {
            a = Ji(c, a);
            a = Qi(b, a, 1);
            b = nh(b, a, 1);
            a = R();
            null !== b && (Ac(b, 1, a), Dk(b, a));
            break;
          }
        }
        b = b.return;
      }
    }
    function Ti(a, b, c) {
      var d = a.pingCache;
      null !== d && d.delete(b);
      b = R();
      a.pingedLanes |= a.suspendedLanes & c;
      Q === a && (Z & c) === c && (4 === T || 3 === T && (Z & 130023424) === Z && 500 > B() - fk ? Kk(a, 0) : rk |= c);
      Dk(a, b);
    }
    function Yk(a, b) {
      0 === b && (0 === (a.mode & 1) ? b = 1 : (b = sc, sc <<= 1, 0 === (sc & 130023424) && (sc = 4194304)));
      var c = R();
      a = ih(a, b);
      null !== a && (Ac(a, b, c), Dk(a, c));
    }
    function uj(a) {
      var b = a.memoizedState, c = 0;
      null !== b && (c = b.retryLane);
      Yk(a, c);
    }
    function bk(a, b) {
      var c = 0;
      switch (a.tag) {
        case 13:
          var d = a.stateNode;
          var e = a.memoizedState;
          null !== e && (c = e.retryLane);
          break;
        case 19:
          d = a.stateNode;
          break;
        default:
          throw Error(p(314));
      }
      null !== d && d.delete(b);
      Yk(a, c);
    }
    var Vk;
    Vk = function(a, b, c) {
      if (null !== a) if (a.memoizedProps !== b.pendingProps || Wf.current) dh = true;
      else {
        if (0 === (a.lanes & c) && 0 === (b.flags & 128)) return dh = false, yj(a, b, c);
        dh = 0 !== (a.flags & 131072) ? true : false;
      }
      else dh = false, I && 0 !== (b.flags & 1048576) && ug(b, ng, b.index);
      b.lanes = 0;
      switch (b.tag) {
        case 2:
          var d = b.type;
          ij(a, b);
          a = b.pendingProps;
          var e = Yf(b, H.current);
          ch(b, c);
          e = Nh(null, b, d, a, e, c);
          var f = Sh();
          b.flags |= 1;
          "object" === typeof e && null !== e && "function" === typeof e.render && void 0 === e.$$typeof ? (b.tag = 1, b.memoizedState = null, b.updateQueue = null, Zf(d) ? (f = true, cg(b)) : f = false, b.memoizedState = null !== e.state && void 0 !== e.state ? e.state : null, kh(b), e.updater = Ei, b.stateNode = e, e._reactInternals = b, Ii(b, d, a, c), b = jj(null, b, d, true, f, c)) : (b.tag = 0, I && f && vg(b), Xi(null, b, e, c), b = b.child);
          return b;
        case 16:
          d = b.elementType;
          a: {
            ij(a, b);
            a = b.pendingProps;
            e = d._init;
            d = e(d._payload);
            b.type = d;
            e = b.tag = Zk(d);
            a = Ci(d, a);
            switch (e) {
              case 0:
                b = cj(null, b, d, a, c);
                break a;
              case 1:
                b = hj(null, b, d, a, c);
                break a;
              case 11:
                b = Yi(null, b, d, a, c);
                break a;
              case 14:
                b = $i(null, b, d, Ci(d.type, a), c);
                break a;
            }
            throw Error(p(
              306,
              d,
              ""
            ));
          }
          return b;
        case 0:
          return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : Ci(d, e), cj(a, b, d, e, c);
        case 1:
          return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : Ci(d, e), hj(a, b, d, e, c);
        case 3:
          a: {
            kj(b);
            if (null === a) throw Error(p(387));
            d = b.pendingProps;
            f = b.memoizedState;
            e = f.element;
            lh(a, b);
            qh(b, d, null, c);
            var g = b.memoizedState;
            d = g.element;
            if (f.isDehydrated) if (f = { element: d, isDehydrated: false, cache: g.cache, pendingSuspenseBoundaries: g.pendingSuspenseBoundaries, transitions: g.transitions }, b.updateQueue.baseState = f, b.memoizedState = f, b.flags & 256) {
              e = Ji(Error(p(423)), b);
              b = lj(a, b, d, c, e);
              break a;
            } else if (d !== e) {
              e = Ji(Error(p(424)), b);
              b = lj(a, b, d, c, e);
              break a;
            } else for (yg = Lf(b.stateNode.containerInfo.firstChild), xg = b, I = true, zg = null, c = Vg(b, null, d, c), b.child = c; c; ) c.flags = c.flags & -3 | 4096, c = c.sibling;
            else {
              Ig();
              if (d === e) {
                b = Zi(a, b, c);
                break a;
              }
              Xi(a, b, d, c);
            }
            b = b.child;
          }
          return b;
        case 5:
          return Ah(b), null === a && Eg(b), d = b.type, e = b.pendingProps, f = null !== a ? a.memoizedProps : null, g = e.children, Ef(d, e) ? g = null : null !== f && Ef(d, f) && (b.flags |= 32), gj(a, b), Xi(a, b, g, c), b.child;
        case 6:
          return null === a && Eg(b), null;
        case 13:
          return oj(a, b, c);
        case 4:
          return yh(b, b.stateNode.containerInfo), d = b.pendingProps, null === a ? b.child = Ug(b, null, d, c) : Xi(a, b, d, c), b.child;
        case 11:
          return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : Ci(d, e), Yi(a, b, d, e, c);
        case 7:
          return Xi(a, b, b.pendingProps, c), b.child;
        case 8:
          return Xi(a, b, b.pendingProps.children, c), b.child;
        case 12:
          return Xi(a, b, b.pendingProps.children, c), b.child;
        case 10:
          a: {
            d = b.type._context;
            e = b.pendingProps;
            f = b.memoizedProps;
            g = e.value;
            G(Wg, d._currentValue);
            d._currentValue = g;
            if (null !== f) if (He(f.value, g)) {
              if (f.children === e.children && !Wf.current) {
                b = Zi(a, b, c);
                break a;
              }
            } else for (f = b.child, null !== f && (f.return = b); null !== f; ) {
              var h = f.dependencies;
              if (null !== h) {
                g = f.child;
                for (var k = h.firstContext; null !== k; ) {
                  if (k.context === d) {
                    if (1 === f.tag) {
                      k = mh(-1, c & -c);
                      k.tag = 2;
                      var l = f.updateQueue;
                      if (null !== l) {
                        l = l.shared;
                        var m = l.pending;
                        null === m ? k.next = k : (k.next = m.next, m.next = k);
                        l.pending = k;
                      }
                    }
                    f.lanes |= c;
                    k = f.alternate;
                    null !== k && (k.lanes |= c);
                    bh(
                      f.return,
                      c,
                      b
                    );
                    h.lanes |= c;
                    break;
                  }
                  k = k.next;
                }
              } else if (10 === f.tag) g = f.type === b.type ? null : f.child;
              else if (18 === f.tag) {
                g = f.return;
                if (null === g) throw Error(p(341));
                g.lanes |= c;
                h = g.alternate;
                null !== h && (h.lanes |= c);
                bh(g, c, b);
                g = f.sibling;
              } else g = f.child;
              if (null !== g) g.return = f;
              else for (g = f; null !== g; ) {
                if (g === b) {
                  g = null;
                  break;
                }
                f = g.sibling;
                if (null !== f) {
                  f.return = g.return;
                  g = f;
                  break;
                }
                g = g.return;
              }
              f = g;
            }
            Xi(a, b, e.children, c);
            b = b.child;
          }
          return b;
        case 9:
          return e = b.type, d = b.pendingProps.children, ch(b, c), e = eh(e), d = d(e), b.flags |= 1, Xi(a, b, d, c), b.child;
        case 14:
          return d = b.type, e = Ci(d, b.pendingProps), e = Ci(d.type, e), $i(a, b, d, e, c);
        case 15:
          return bj(a, b, b.type, b.pendingProps, c);
        case 17:
          return d = b.type, e = b.pendingProps, e = b.elementType === d ? e : Ci(d, e), ij(a, b), b.tag = 1, Zf(d) ? (a = true, cg(b)) : a = false, ch(b, c), Gi(b, d, e), Ii(b, d, e, c), jj(null, b, d, true, a, c);
        case 19:
          return xj(a, b, c);
        case 22:
          return dj(a, b, c);
      }
      throw Error(p(156, b.tag));
    };
    function Fk(a, b) {
      return ac(a, b);
    }
    function $k(a, b, c, d) {
      this.tag = a;
      this.key = c;
      this.sibling = this.child = this.return = this.stateNode = this.type = this.elementType = null;
      this.index = 0;
      this.ref = null;
      this.pendingProps = b;
      this.dependencies = this.memoizedState = this.updateQueue = this.memoizedProps = null;
      this.mode = d;
      this.subtreeFlags = this.flags = 0;
      this.deletions = null;
      this.childLanes = this.lanes = 0;
      this.alternate = null;
    }
    function Bg(a, b, c, d) {
      return new $k(a, b, c, d);
    }
    function aj(a) {
      a = a.prototype;
      return !(!a || !a.isReactComponent);
    }
    function Zk(a) {
      if ("function" === typeof a) return aj(a) ? 1 : 0;
      if (void 0 !== a && null !== a) {
        a = a.$$typeof;
        if (a === Da) return 11;
        if (a === Ga) return 14;
      }
      return 2;
    }
    function Pg(a, b) {
      var c = a.alternate;
      null === c ? (c = Bg(a.tag, b, a.key, a.mode), c.elementType = a.elementType, c.type = a.type, c.stateNode = a.stateNode, c.alternate = a, a.alternate = c) : (c.pendingProps = b, c.type = a.type, c.flags = 0, c.subtreeFlags = 0, c.deletions = null);
      c.flags = a.flags & 14680064;
      c.childLanes = a.childLanes;
      c.lanes = a.lanes;
      c.child = a.child;
      c.memoizedProps = a.memoizedProps;
      c.memoizedState = a.memoizedState;
      c.updateQueue = a.updateQueue;
      b = a.dependencies;
      c.dependencies = null === b ? null : { lanes: b.lanes, firstContext: b.firstContext };
      c.sibling = a.sibling;
      c.index = a.index;
      c.ref = a.ref;
      return c;
    }
    function Rg(a, b, c, d, e, f) {
      var g = 2;
      d = a;
      if ("function" === typeof a) aj(a) && (g = 1);
      else if ("string" === typeof a) g = 5;
      else a: switch (a) {
        case ya:
          return Tg(c.children, e, f, b);
        case za:
          g = 8;
          e |= 8;
          break;
        case Aa:
          return a = Bg(12, c, b, e | 2), a.elementType = Aa, a.lanes = f, a;
        case Ea:
          return a = Bg(13, c, b, e), a.elementType = Ea, a.lanes = f, a;
        case Fa:
          return a = Bg(19, c, b, e), a.elementType = Fa, a.lanes = f, a;
        case Ia:
          return pj(c, e, f, b);
        default:
          if ("object" === typeof a && null !== a) switch (a.$$typeof) {
            case Ba:
              g = 10;
              break a;
            case Ca:
              g = 9;
              break a;
            case Da:
              g = 11;
              break a;
            case Ga:
              g = 14;
              break a;
            case Ha:
              g = 16;
              d = null;
              break a;
          }
          throw Error(p(130, null == a ? a : typeof a, ""));
      }
      b = Bg(g, c, b, e);
      b.elementType = a;
      b.type = d;
      b.lanes = f;
      return b;
    }
    function Tg(a, b, c, d) {
      a = Bg(7, a, d, b);
      a.lanes = c;
      return a;
    }
    function pj(a, b, c, d) {
      a = Bg(22, a, d, b);
      a.elementType = Ia;
      a.lanes = c;
      a.stateNode = { isHidden: false };
      return a;
    }
    function Qg(a, b, c) {
      a = Bg(6, a, null, b);
      a.lanes = c;
      return a;
    }
    function Sg(a, b, c) {
      b = Bg(4, null !== a.children ? a.children : [], a.key, b);
      b.lanes = c;
      b.stateNode = { containerInfo: a.containerInfo, pendingChildren: null, implementation: a.implementation };
      return b;
    }
    function al(a, b, c, d, e) {
      this.tag = b;
      this.containerInfo = a;
      this.finishedWork = this.pingCache = this.current = this.pendingChildren = null;
      this.timeoutHandle = -1;
      this.callbackNode = this.pendingContext = this.context = null;
      this.callbackPriority = 0;
      this.eventTimes = zc(0);
      this.expirationTimes = zc(-1);
      this.entangledLanes = this.finishedLanes = this.mutableReadLanes = this.expiredLanes = this.pingedLanes = this.suspendedLanes = this.pendingLanes = 0;
      this.entanglements = zc(0);
      this.identifierPrefix = d;
      this.onRecoverableError = e;
      this.mutableSourceEagerHydrationData = null;
    }
    function bl(a, b, c, d, e, f, g, h, k) {
      a = new al(a, b, c, h, k);
      1 === b ? (b = 1, true === f && (b |= 8)) : b = 0;
      f = Bg(3, null, null, b);
      a.current = f;
      f.stateNode = a;
      f.memoizedState = { element: d, isDehydrated: c, cache: null, transitions: null, pendingSuspenseBoundaries: null };
      kh(f);
      return a;
    }
    function cl(a, b, c) {
      var d = 3 < arguments.length && void 0 !== arguments[3] ? arguments[3] : null;
      return { $$typeof: wa, key: null == d ? null : "" + d, children: a, containerInfo: b, implementation: c };
    }
    function dl(a) {
      if (!a) return Vf;
      a = a._reactInternals;
      a: {
        if (Vb(a) !== a || 1 !== a.tag) throw Error(p(170));
        var b = a;
        do {
          switch (b.tag) {
            case 3:
              b = b.stateNode.context;
              break a;
            case 1:
              if (Zf(b.type)) {
                b = b.stateNode.__reactInternalMemoizedMergedChildContext;
                break a;
              }
          }
          b = b.return;
        } while (null !== b);
        throw Error(p(171));
      }
      if (1 === a.tag) {
        var c = a.type;
        if (Zf(c)) return bg(a, c, b);
      }
      return b;
    }
    function el(a, b, c, d, e, f, g, h, k) {
      a = bl(c, d, true, a, e, f, g, h, k);
      a.context = dl(null);
      c = a.current;
      d = R();
      e = yi(c);
      f = mh(d, e);
      f.callback = void 0 !== b && null !== b ? b : null;
      nh(c, f, e);
      a.current.lanes = e;
      Ac(a, e, d);
      Dk(a, d);
      return a;
    }
    function fl(a, b, c, d) {
      var e = b.current, f = R(), g = yi(e);
      c = dl(c);
      null === b.context ? b.context = c : b.pendingContext = c;
      b = mh(f, g);
      b.payload = { element: a };
      d = void 0 === d ? null : d;
      null !== d && (b.callback = d);
      a = nh(e, b, g);
      null !== a && (gi(a, e, g, f), oh(a, e, g));
      return g;
    }
    function gl(a) {
      a = a.current;
      if (!a.child) return null;
      switch (a.child.tag) {
        case 5:
          return a.child.stateNode;
        default:
          return a.child.stateNode;
      }
    }
    function hl(a, b) {
      a = a.memoizedState;
      if (null !== a && null !== a.dehydrated) {
        var c = a.retryLane;
        a.retryLane = 0 !== c && c < b ? c : b;
      }
    }
    function il(a, b) {
      hl(a, b);
      (a = a.alternate) && hl(a, b);
    }
    function jl() {
      return null;
    }
    var kl = "function" === typeof reportError ? reportError : function(a) {
      console.error(a);
    };
    function ll(a) {
      this._internalRoot = a;
    }
    ml.prototype.render = ll.prototype.render = function(a) {
      var b = this._internalRoot;
      if (null === b) throw Error(p(409));
      fl(a, b, null, null);
    };
    ml.prototype.unmount = ll.prototype.unmount = function() {
      var a = this._internalRoot;
      if (null !== a) {
        this._internalRoot = null;
        var b = a.containerInfo;
        Rk(function() {
          fl(null, a, null, null);
        });
        b[uf] = null;
      }
    };
    function ml(a) {
      this._internalRoot = a;
    }
    ml.prototype.unstable_scheduleHydration = function(a) {
      if (a) {
        var b = Hc();
        a = { blockedOn: null, target: a, priority: b };
        for (var c = 0; c < Qc.length && 0 !== b && b < Qc[c].priority; c++) ;
        Qc.splice(c, 0, a);
        0 === c && Vc(a);
      }
    };
    function nl(a) {
      return !(!a || 1 !== a.nodeType && 9 !== a.nodeType && 11 !== a.nodeType);
    }
    function ol(a) {
      return !(!a || 1 !== a.nodeType && 9 !== a.nodeType && 11 !== a.nodeType && (8 !== a.nodeType || " react-mount-point-unstable " !== a.nodeValue));
    }
    function pl() {
    }
    function ql(a, b, c, d, e) {
      if (e) {
        if ("function" === typeof d) {
          var f = d;
          d = function() {
            var a2 = gl(g);
            f.call(a2);
          };
        }
        var g = el(b, d, a, 0, null, false, false, "", pl);
        a._reactRootContainer = g;
        a[uf] = g.current;
        sf(8 === a.nodeType ? a.parentNode : a);
        Rk();
        return g;
      }
      for (; e = a.lastChild; ) a.removeChild(e);
      if ("function" === typeof d) {
        var h = d;
        d = function() {
          var a2 = gl(k);
          h.call(a2);
        };
      }
      var k = bl(a, 0, false, null, null, false, false, "", pl);
      a._reactRootContainer = k;
      a[uf] = k.current;
      sf(8 === a.nodeType ? a.parentNode : a);
      Rk(function() {
        fl(b, k, c, d);
      });
      return k;
    }
    function rl(a, b, c, d, e) {
      var f = c._reactRootContainer;
      if (f) {
        var g = f;
        if ("function" === typeof e) {
          var h = e;
          e = function() {
            var a2 = gl(g);
            h.call(a2);
          };
        }
        fl(b, g, a, e);
      } else g = ql(c, b, a, e, d);
      return gl(g);
    }
    Ec = function(a) {
      switch (a.tag) {
        case 3:
          var b = a.stateNode;
          if (b.current.memoizedState.isDehydrated) {
            var c = tc(b.pendingLanes);
            0 !== c && (Cc(b, c | 1), Dk(b, B()), 0 === (K & 6) && (Gj = B() + 500, jg()));
          }
          break;
        case 13:
          Rk(function() {
            var b2 = ih(a, 1);
            if (null !== b2) {
              var c2 = R();
              gi(b2, a, 1, c2);
            }
          }), il(a, 1);
      }
    };
    Fc = function(a) {
      if (13 === a.tag) {
        var b = ih(a, 134217728);
        if (null !== b) {
          var c = R();
          gi(b, a, 134217728, c);
        }
        il(a, 134217728);
      }
    };
    Gc = function(a) {
      if (13 === a.tag) {
        var b = yi(a), c = ih(a, b);
        if (null !== c) {
          var d = R();
          gi(c, a, b, d);
        }
        il(a, b);
      }
    };
    Hc = function() {
      return C;
    };
    Ic = function(a, b) {
      var c = C;
      try {
        return C = a, b();
      } finally {
        C = c;
      }
    };
    yb = function(a, b, c) {
      switch (b) {
        case "input":
          bb(a, c);
          b = c.name;
          if ("radio" === c.type && null != b) {
            for (c = a; c.parentNode; ) c = c.parentNode;
            c = c.querySelectorAll("input[name=" + JSON.stringify("" + b) + '][type="radio"]');
            for (b = 0; b < c.length; b++) {
              var d = c[b];
              if (d !== a && d.form === a.form) {
                var e = Db(d);
                if (!e) throw Error(p(90));
                Wa(d);
                bb(d, e);
              }
            }
          }
          break;
        case "textarea":
          ib(a, c);
          break;
        case "select":
          b = c.value, null != b && fb(a, !!c.multiple, b, false);
      }
    };
    Gb = Qk;
    Hb = Rk;
    var sl = { usingClientEntryPoint: false, Events: [Cb, ue, Db, Eb, Fb, Qk] }, tl = { findFiberByHostInstance: Wc, bundleType: 0, version: "18.3.1", rendererPackageName: "react-dom" };
    var ul = { bundleType: tl.bundleType, version: tl.version, rendererPackageName: tl.rendererPackageName, rendererConfig: tl.rendererConfig, overrideHookState: null, overrideHookStateDeletePath: null, overrideHookStateRenamePath: null, overrideProps: null, overridePropsDeletePath: null, overridePropsRenamePath: null, setErrorHandler: null, setSuspenseHandler: null, scheduleUpdate: null, currentDispatcherRef: ua.ReactCurrentDispatcher, findHostInstanceByFiber: function(a) {
      a = Zb(a);
      return null === a ? null : a.stateNode;
    }, findFiberByHostInstance: tl.findFiberByHostInstance || jl, findHostInstancesForRefresh: null, scheduleRefresh: null, scheduleRoot: null, setRefreshHandler: null, getCurrentFiber: null, reconcilerVersion: "18.3.1-next-f1338f8080-20240426" };
    if ("undefined" !== typeof __REACT_DEVTOOLS_GLOBAL_HOOK__) {
      var vl = __REACT_DEVTOOLS_GLOBAL_HOOK__;
      if (!vl.isDisabled && vl.supportsFiber) try {
        kc = vl.inject(ul), lc = vl;
      } catch (a) {
      }
    }
    reactDom_production_min.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED = sl;
    reactDom_production_min.createPortal = function(a, b) {
      var c = 2 < arguments.length && void 0 !== arguments[2] ? arguments[2] : null;
      if (!nl(b)) throw Error(p(200));
      return cl(a, b, null, c);
    };
    reactDom_production_min.createRoot = function(a, b) {
      if (!nl(a)) throw Error(p(299));
      var c = false, d = "", e = kl;
      null !== b && void 0 !== b && (true === b.unstable_strictMode && (c = true), void 0 !== b.identifierPrefix && (d = b.identifierPrefix), void 0 !== b.onRecoverableError && (e = b.onRecoverableError));
      b = bl(a, 1, false, null, null, c, false, d, e);
      a[uf] = b.current;
      sf(8 === a.nodeType ? a.parentNode : a);
      return new ll(b);
    };
    reactDom_production_min.findDOMNode = function(a) {
      if (null == a) return null;
      if (1 === a.nodeType) return a;
      var b = a._reactInternals;
      if (void 0 === b) {
        if ("function" === typeof a.render) throw Error(p(188));
        a = Object.keys(a).join(",");
        throw Error(p(268, a));
      }
      a = Zb(b);
      a = null === a ? null : a.stateNode;
      return a;
    };
    reactDom_production_min.flushSync = function(a) {
      return Rk(a);
    };
    reactDom_production_min.hydrate = function(a, b, c) {
      if (!ol(b)) throw Error(p(200));
      return rl(null, a, b, true, c);
    };
    reactDom_production_min.hydrateRoot = function(a, b, c) {
      if (!nl(a)) throw Error(p(405));
      var d = null != c && c.hydratedSources || null, e = false, f = "", g = kl;
      null !== c && void 0 !== c && (true === c.unstable_strictMode && (e = true), void 0 !== c.identifierPrefix && (f = c.identifierPrefix), void 0 !== c.onRecoverableError && (g = c.onRecoverableError));
      b = el(b, null, a, 1, null != c ? c : null, e, false, f, g);
      a[uf] = b.current;
      sf(a);
      if (d) for (a = 0; a < d.length; a++) c = d[a], e = c._getVersion, e = e(c._source), null == b.mutableSourceEagerHydrationData ? b.mutableSourceEagerHydrationData = [c, e] : b.mutableSourceEagerHydrationData.push(
        c,
        e
      );
      return new ml(b);
    };
    reactDom_production_min.render = function(a, b, c) {
      if (!ol(b)) throw Error(p(200));
      return rl(null, a, b, false, c);
    };
    reactDom_production_min.unmountComponentAtNode = function(a) {
      if (!ol(a)) throw Error(p(40));
      return a._reactRootContainer ? (Rk(function() {
        rl(null, null, a, false, function() {
          a._reactRootContainer = null;
          a[uf] = null;
        });
      }), true) : false;
    };
    reactDom_production_min.unstable_batchedUpdates = Qk;
    reactDom_production_min.unstable_renderSubtreeIntoContainer = function(a, b, c, d) {
      if (!ol(c)) throw Error(p(200));
      if (null == a || void 0 === a._reactInternals) throw Error(p(38));
      return rl(a, b, c, false, d);
    };
    reactDom_production_min.version = "18.3.1-next-f1338f8080-20240426";
    return reactDom_production_min;
  }
  var hasRequiredReactDom;
  function requireReactDom() {
    if (hasRequiredReactDom) return reactDom.exports;
    hasRequiredReactDom = 1;
    function checkDCE() {
      if (typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ === "undefined" || typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE !== "function") {
        return;
      }
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(checkDCE);
      } catch (err) {
        console.error(err);
      }
    }
    {
      checkDCE();
      reactDom.exports = requireReactDom_production_min();
    }
    return reactDom.exports;
  }
  var hasRequiredClient;
  function requireClient() {
    if (hasRequiredClient) return client;
    hasRequiredClient = 1;
    var m = requireReactDom();
    {
      client.createRoot = m.createRoot;
      client.hydrateRoot = m.hydrateRoot;
    }
    return client;
  }
  var clientExports = requireClient();
  function uuid() {
    const cryptoValue = globalThis.crypto;
    if (cryptoValue == null ? void 0 : cryptoValue.randomUUID) {
      return cryptoValue.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
      const value = Math.random() * 16 | 0;
      const next = char === "x" ? value : value & 3 | 8;
      return next.toString(16);
    });
  }
  function clone(value) {
    if (value === void 0 || value === null) {
      return value;
    }
    return JSON.parse(JSON.stringify(value));
  }
  function asText(value) {
    if (typeof value === "string") {
      return value;
    }
    if (Array.isArray(value)) {
      return value.map((part) => {
        if (typeof part === "string") {
          return part;
        }
        if (part && typeof part === "object") {
          const item = part;
          return item.text ?? item.content ?? item.value ?? "";
        }
        return "";
      }).join("");
    }
    if (value && typeof value === "object") {
      return JSON.stringify(value, null, 2);
    }
    return value === void 0 || value === null ? "" : String(value);
  }
  function textSummary(value, limit = 80) {
    const text2 = asText(value).replace(/\s+/g, " ").trim();
    if (!limit || text2.length <= limit) {
      return text2;
    }
    return `${text2.slice(0, limit - 1)}...`;
  }
  function parseJson(value) {
    if (!value || typeof value !== "string") {
      return value || {};
    }
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }
  function shortHash(value) {
    let text2 = "";
    let result = 0;
    try {
      text2 = JSON.stringify(value);
    } catch {
      text2 = String(value || "");
    }
    for (let index2 = 0; index2 < text2.length; index2 += 1) {
      result = (result << 5) - result + text2.charCodeAt(index2);
      result &= result;
    }
    return (result >>> 0).toString(36);
  }
  function statusFromResult(result, fallback = "pending") {
    const value = result && typeof result === "object" ? result : {};
    if (value.cancelled) {
      return "cancelled";
    }
    if (value.needs_confirmation) {
      return "needs_confirmation";
    }
    if (value.ok === false || value.error) {
      return "error";
    }
    if (value.ok === true) {
      return "ok";
    }
    return fallback;
  }
  function statusRank(status) {
    return {
      pending: 1,
      running: 2,
      needs_confirmation: 3,
      ok: 4,
      error: 4,
      cancelled: 4
    }[status || "pending"] || 1;
  }
  function mergeStatus(existing, incoming) {
    if (!existing) {
      return incoming || "pending";
    }
    return statusRank(incoming) >= statusRank(existing) ? incoming : existing;
  }
  function toolCallId(tool) {
    return String(tool.id || tool.tool_call_id || tool.toolCallId || "");
  }
  function toolName(tool) {
    return String(tool.name || tool.tool_name || tool.tool || "unknown");
  }
  function toolArgs(tool) {
    return tool.args ?? tool.tool_args ?? parseJson(tool.argsText || "{}");
  }
  function toolKey(tool) {
    const id = toolCallId(tool);
    const name2 = toolName(tool);
    const args = toolArgs(tool);
    if (id) {
      return `id:${id}`;
    }
    if (tool.createdAt || tool.created_at) {
      return `created:${name2}:${tool.createdAt || tool.created_at}`;
    }
    return `sig:${name2}:${shortHash(args)}`;
  }
  function normalizeReferenceGroups(value) {
    if (!Array.isArray(value)) {
      return [];
    }
    return value.map((rawGroup) => {
      const group = rawGroup && typeof rawGroup === "object" ? rawGroup : {};
      const source = Array.isArray(group.references) ? group.references : [group];
      const references = source.map((rawReference) => {
        const reference = rawReference && typeof rawReference === "object" ? rawReference : {};
        const content2 = reference.content || reference.text || reference.summary || reference.description || "";
        const name2 = reference.name || reference.title || reference.url || "";
        const url = reference.url || reference.link || "";
        if (!content2 && !name2 && !url) {
          return null;
        }
        return {
          name: String(name2 || textSummary(content2, 60)),
          url: url ? String(url) : void 0,
          content: textSummary(content2, 180),
          meta_data: reference.meta_data && typeof reference.meta_data === "object" ? reference.meta_data : void 0
        };
      }).filter(Boolean);
      if (!references.length) {
        return null;
      }
      return {
        query: group.query ? String(group.query) : "",
        references
      };
    }).filter(Boolean);
  }
  function visibleMessages(messages) {
    return messages.filter((message) => {
      if (message.hidden) {
        return false;
      }
      if (message.role === "tool" && (message.toolCallId || message.tool_call_id)) {
        return false;
      }
      return true;
    });
  }
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const toKebabCase = (string2) => string2.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
  const mergeClasses = (...classes) => classes.filter((className, index2, array) => {
    return Boolean(className) && className.trim() !== "" && array.indexOf(className) === index2;
  }).join(" ").trim();
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  var defaultAttributes = {
    xmlns: "http://www.w3.org/2000/svg",
    width: 24,
    height: 24,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round"
  };
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const Icon = reactExports.forwardRef(
    ({
      color: color2 = "currentColor",
      size = 24,
      strokeWidth = 2,
      absoluteStrokeWidth,
      className = "",
      children,
      iconNode,
      ...rest
    }, ref) => {
      return reactExports.createElement(
        "svg",
        {
          ref,
          ...defaultAttributes,
          width: size,
          height: size,
          stroke: color2,
          strokeWidth: absoluteStrokeWidth ? Number(strokeWidth) * 24 / Number(size) : strokeWidth,
          className: mergeClasses("lucide", className),
          ...rest
        },
        [
          ...iconNode.map(([tag, attrs]) => reactExports.createElement(tag, attrs)),
          ...Array.isArray(children) ? children : [children]
        ]
      );
    }
  );
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const createLucideIcon = (iconName, iconNode) => {
    const Component = reactExports.forwardRef(
      ({ className, ...props }, ref) => reactExports.createElement(Icon, {
        ref,
        iconNode,
        className: mergeClasses(`lucide-${toKebabCase(iconName)}`, className),
        ...props
      })
    );
    Component.displayName = `${iconName}`;
    return Component;
  };
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$F = [
    ["rect", { width: "20", height: "5", x: "2", y: "3", rx: "1", key: "1wp1u1" }],
    ["path", { d: "M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8", key: "1s80jp" }],
    ["path", { d: "M10 12h4", key: "a56b0p" }]
  ];
  const Archive = createLucideIcon("Archive", __iconNode$F);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$E = [
    ["path", { d: "m12 19-7-7 7-7", key: "1l729n" }],
    ["path", { d: "M19 12H5", key: "x3x0zl" }]
  ];
  const ArrowLeft = createLucideIcon("ArrowLeft", __iconNode$E);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$D = [
    ["circle", { cx: "12", cy: "12", r: "4", key: "4exip2" }],
    ["path", { d: "M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8", key: "7n84p3" }]
  ];
  const AtSign = createLucideIcon("AtSign", __iconNode$D);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$C = [["path", { d: "M20 6 9 17l-5-5", key: "1gmf2c" }]];
  const Check = createLucideIcon("Check", __iconNode$C);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$B = [["path", { d: "m9 18 6-6-6-6", key: "mthhwq" }]];
  const ChevronRight = createLucideIcon("ChevronRight", __iconNode$B);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$A = [
    ["path", { d: "m11 17-5-5 5-5", key: "13zhaf" }],
    ["path", { d: "m18 17-5-5 5-5", key: "h8a8et" }]
  ];
  const ChevronsLeft = createLucideIcon("ChevronsLeft", __iconNode$A);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$z = [
    ["path", { d: "m6 17 5-5-5-5", key: "xnjwq" }],
    ["path", { d: "m13 17 5-5-5-5", key: "17xmmf" }]
  ];
  const ChevronsRight = createLucideIcon("ChevronsRight", __iconNode$z);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$y = [
    ["circle", { cx: "12", cy: "12", r: "10", key: "1mglay" }],
    ["line", { x1: "12", x2: "12", y1: "8", y2: "12", key: "1pkeuh" }],
    ["line", { x1: "12", x2: "12.01", y1: "16", y2: "16", key: "4dfq90" }]
  ];
  const CircleAlert = createLucideIcon("CircleAlert", __iconNode$y);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$x = [
    ["circle", { cx: "12", cy: "12", r: "10", key: "1mglay" }],
    ["path", { d: "m9 12 2 2 4-4", key: "dzmm74" }]
  ];
  const CircleCheck = createLucideIcon("CircleCheck", __iconNode$x);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$w = [
    ["circle", { cx: "12", cy: "12", r: "10", key: "1mglay" }],
    ["polyline", { points: "12 6 12 12 16.5 12", key: "1aq6pp" }]
  ];
  const Clock3 = createLucideIcon("Clock3", __iconNode$w);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$v = [
    ["path", { d: "M12 13v8", key: "1l5pq0" }],
    ["path", { d: "M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242", key: "1pljnt" }],
    ["path", { d: "m8 17 4-4 4 4", key: "1quai1" }]
  ];
  const CloudUpload = createLucideIcon("CloudUpload", __iconNode$v);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$u = [
    ["rect", { width: "14", height: "14", x: "8", y: "8", rx: "2", ry: "2", key: "17jyea" }],
    ["path", { d: "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2", key: "zix9uf" }]
  ];
  const Copy = createLucideIcon("Copy", __iconNode$u);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$t = [
    ["ellipse", { cx: "12", cy: "5", rx: "9", ry: "3", key: "msslwz" }],
    ["path", { d: "M3 5V19A9 3 0 0 0 21 19V5", key: "1wlel7" }],
    ["path", { d: "M3 12A9 3 0 0 0 21 12", key: "mv7ke4" }]
  ];
  const Database = createLucideIcon("Database", __iconNode$t);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$s = [
    ["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", key: "ih7n3h" }],
    ["polyline", { points: "7 10 12 15 17 10", key: "2ggqvy" }],
    ["line", { x1: "12", x2: "12", y1: "15", y2: "3", key: "1vk2je" }]
  ];
  const Download = createLucideIcon("Download", __iconNode$s);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$r = [
    ["path", { d: "M15 3h6v6", key: "1q9fwt" }],
    ["path", { d: "M10 14 21 3", key: "gplh6r" }],
    ["path", { d: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6", key: "a6xqqp" }]
  ];
  const ExternalLink = createLucideIcon("ExternalLink", __iconNode$r);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$q = [
    [
      "path",
      {
        d: "M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0",
        key: "1nclc0"
      }
    ],
    ["circle", { cx: "12", cy: "12", r: "3", key: "1v7zrd" }]
  ];
  const Eye = createLucideIcon("Eye", __iconNode$q);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$p = [
    ["path", { d: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z", key: "1rqfz7" }],
    ["path", { d: "M14 2v4a2 2 0 0 0 2 2h4", key: "tnqrlb" }],
    ["path", { d: "M10 9H8", key: "b1mrlr" }],
    ["path", { d: "M16 13H8", key: "t4e002" }],
    ["path", { d: "M16 17H8", key: "z1uh3a" }]
  ];
  const FileText = createLucideIcon("FileText", __iconNode$p);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$o = [
    ["path", { d: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z", key: "1rqfz7" }],
    ["path", { d: "M14 2v4a2 2 0 0 0 2 2h4", key: "tnqrlb" }]
  ];
  const File = createLucideIcon("File", __iconNode$o);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$n = [
    ["polygon", { points: "22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3", key: "1yg77f" }]
  ];
  const Filter = createLucideIcon("Filter", __iconNode$n);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$m = [
    [
      "path",
      {
        d: "m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2",
        key: "usdka0"
      }
    ]
  ];
  const FolderOpen = createLucideIcon("FolderOpen", __iconNode$m);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$l = [
    [
      "path",
      {
        d: "M20 10a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-2.5a1 1 0 0 1-.8-.4l-.9-1.2A1 1 0 0 0 15 3h-2a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1Z",
        key: "hod4my"
      }
    ],
    [
      "path",
      {
        d: "M20 21a1 1 0 0 0 1-1v-3a1 1 0 0 0-1-1h-2.9a1 1 0 0 1-.88-.55l-.42-.85a1 1 0 0 0-.92-.6H13a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1Z",
        key: "w4yl2u"
      }
    ],
    ["path", { d: "M3 5a2 2 0 0 0 2 2h3", key: "f2jnh7" }],
    ["path", { d: "M3 3v13a2 2 0 0 0 2 2h3", key: "k8epm1" }]
  ];
  const FolderTree = createLucideIcon("FolderTree", __iconNode$l);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$k = [
    [
      "path",
      {
        d: "M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z",
        key: "1kt360"
      }
    ]
  ];
  const Folder = createLucideIcon("Folder", __iconNode$k);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$j = [
    ["circle", { cx: "9", cy: "12", r: "1", key: "1vctgf" }],
    ["circle", { cx: "9", cy: "5", r: "1", key: "hp0tcf" }],
    ["circle", { cx: "9", cy: "19", r: "1", key: "fkjjf6" }],
    ["circle", { cx: "15", cy: "12", r: "1", key: "1tmaij" }],
    ["circle", { cx: "15", cy: "5", r: "1", key: "19l28e" }],
    ["circle", { cx: "15", cy: "19", r: "1", key: "f4zoj3" }]
  ];
  const GripVertical = createLucideIcon("GripVertical", __iconNode$j);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$i = [
    ["path", { d: "m15 12-8.373 8.373a1 1 0 1 1-3-3L12 9", key: "eefl8a" }],
    ["path", { d: "m18 15 4-4", key: "16gjal" }],
    [
      "path",
      {
        d: "m21.5 11.5-1.914-1.914A2 2 0 0 1 19 8.172V7l-2.26-2.26a6 6 0 0 0-4.202-1.756L9 2.96l.92.82A6.18 6.18 0 0 1 12 8.4V10l2 2h1.172a2 2 0 0 1 1.414.586L18.5 14.5",
        key: "b7pghm"
      }
    ]
  ];
  const Hammer = createLucideIcon("Hammer", __iconNode$i);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$h = [["path", { d: "M21 12a9 9 0 1 1-6.219-8.56", key: "13zald" }]];
  const LoaderCircle = createLucideIcon("LoaderCircle", __iconNode$h);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$g = [
    ["line", { x1: "4", x2: "20", y1: "12", y2: "12", key: "1e0a9i" }],
    ["line", { x1: "4", x2: "20", y1: "6", y2: "6", key: "1owob3" }],
    ["line", { x1: "4", x2: "20", y1: "18", y2: "18", key: "yk5zj1" }]
  ];
  const Menu = createLucideIcon("Menu", __iconNode$g);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$f = [
    ["path", { d: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z", key: "1lielz" }],
    ["path", { d: "M12 7v6", key: "lw1j43" }],
    ["path", { d: "M9 10h6", key: "9gxzsh" }]
  ];
  const MessageSquarePlus = createLucideIcon("MessageSquarePlus", __iconNode$f);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$e = [
    ["path", { d: "M13.234 20.252 21 12.3", key: "1cbrk9" }],
    [
      "path",
      {
        d: "m16 6-8.414 8.586a2 2 0 0 0 0 2.828 2 2 0 0 0 2.828 0l8.414-8.586a4 4 0 0 0 0-5.656 4 4 0 0 0-5.656 0l-8.415 8.585a6 6 0 1 0 8.486 8.486",
        key: "1pkts6"
      }
    ]
  ];
  const Paperclip = createLucideIcon("Paperclip", __iconNode$e);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$d = [
    [
      "path",
      {
        d: "M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z",
        key: "1a8usu"
      }
    ],
    ["path", { d: "m15 5 4 4", key: "1mk7zo" }]
  ];
  const Pencil = createLucideIcon("Pencil", __iconNode$d);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$c = [
    ["path", { d: "M5 12h14", key: "1ays0h" }],
    ["path", { d: "M12 5v14", key: "s699le" }]
  ];
  const Plus = createLucideIcon("Plus", __iconNode$c);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$b = [
    ["path", { d: "M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8", key: "14sxne" }],
    ["path", { d: "M3 3v5h5", key: "1xhq8a" }],
    ["path", { d: "M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16", key: "1hlbsb" }],
    ["path", { d: "M16 16h5v5", key: "ccwih5" }]
  ];
  const RefreshCcw = createLucideIcon("RefreshCcw", __iconNode$b);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$a = [
    ["path", { d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", key: "v9h5vc" }],
    ["path", { d: "M21 3v5h-5", key: "1q7to0" }],
    ["path", { d: "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", key: "3uifl3" }],
    ["path", { d: "M8 16H3v5", key: "1cv678" }]
  ];
  const RefreshCw = createLucideIcon("RefreshCw", __iconNode$a);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$9 = [
    ["path", { d: "M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8", key: "1357e3" }],
    ["path", { d: "M3 3v5h5", key: "1xhq8a" }]
  ];
  const RotateCcw = createLucideIcon("RotateCcw", __iconNode$9);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$8 = [
    ["circle", { cx: "11", cy: "11", r: "8", key: "4ej97u" }],
    ["path", { d: "m21 21-4.3-4.3", key: "1qie3q" }]
  ];
  const Search = createLucideIcon("Search", __iconNode$8);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$7 = [
    [
      "path",
      {
        d: "M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z",
        key: "1ffxy3"
      }
    ],
    ["path", { d: "m21.854 2.147-10.94 10.939", key: "12cjpa" }]
  ];
  const Send = createLucideIcon("Send", __iconNode$7);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$6 = [
    ["line", { x1: "21", x2: "14", y1: "4", y2: "4", key: "obuewd" }],
    ["line", { x1: "10", x2: "3", y1: "4", y2: "4", key: "1q6298" }],
    ["line", { x1: "21", x2: "12", y1: "12", y2: "12", key: "1iu8h1" }],
    ["line", { x1: "8", x2: "3", y1: "12", y2: "12", key: "ntss68" }],
    ["line", { x1: "21", x2: "16", y1: "20", y2: "20", key: "14d8ph" }],
    ["line", { x1: "12", x2: "3", y1: "20", y2: "20", key: "m0wm8r" }],
    ["line", { x1: "14", x2: "14", y1: "2", y2: "6", key: "14e1ph" }],
    ["line", { x1: "8", x2: "8", y1: "10", y2: "14", key: "1i6ji0" }],
    ["line", { x1: "16", x2: "16", y1: "18", y2: "22", key: "1lctlv" }]
  ];
  const SlidersHorizontal = createLucideIcon("SlidersHorizontal", __iconNode$6);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$5 = [
    [
      "path",
      {
        d: "M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z",
        key: "4pj2yx"
      }
    ],
    ["path", { d: "M20 3v4", key: "1olli1" }],
    ["path", { d: "M22 5h-4", key: "1gvqau" }],
    ["path", { d: "M4 17v2", key: "vumght" }],
    ["path", { d: "M5 18H3", key: "zchphs" }]
  ];
  const Sparkles = createLucideIcon("Sparkles", __iconNode$5);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$4 = [
    ["rect", { width: "18", height: "18", x: "3", y: "3", rx: "2", key: "afitv7" }]
  ];
  const Square = createLucideIcon("Square", __iconNode$4);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$3 = [
    ["path", { d: "M3 6h18", key: "d0wm0j" }],
    ["path", { d: "M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6", key: "4alrt4" }],
    ["path", { d: "M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2", key: "v07s0e" }],
    ["line", { x1: "10", x2: "10", y1: "11", y2: "17", key: "1uufr5" }],
    ["line", { x1: "14", x2: "14", y1: "11", y2: "17", key: "xtxkd" }]
  ];
  const Trash2 = createLucideIcon("Trash2", __iconNode$3);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$2 = [
    ["path", { d: "M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2", key: "975kel" }],
    ["circle", { cx: "12", cy: "7", r: "4", key: "17ys0d" }]
  ];
  const User = createLucideIcon("User", __iconNode$2);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode$1 = [
    ["rect", { width: "8", height: "8", x: "3", y: "3", rx: "2", key: "by2w9f" }],
    ["path", { d: "M7 11v4a2 2 0 0 0 2 2h4", key: "xkn7yn" }],
    ["rect", { width: "8", height: "8", x: "13", y: "13", rx: "2", key: "1cgmvn" }]
  ];
  const Workflow = createLucideIcon("Workflow", __iconNode$1);
  /**
   * @license lucide-react v0.475.0 - ISC
   *
   * This source code is licensed under the ISC license.
   * See the LICENSE file in the root directory of this source tree.
   */
  const __iconNode = [
    ["path", { d: "M18 6 6 18", key: "1bl5f8" }],
    ["path", { d: "m6 6 12 12", key: "d8bk6v" }]
  ];
  const X = createLucideIcon("X", __iconNode);
  const defaultLabels = {
    inputPlaceholder: "输入消息，@ 选择记录、菜单或技能",
    emptyTitle: "智能助手",
    emptyDescription: "询问当前 Odoo 记录、选中内容或操作。",
    newSession: "新建对话",
    copyResponse: "复制回复",
    copied: "已复制",
    regenerateResponse: "重新生成",
    approve: "批准",
    reject: "拒绝",
    attachments: "附件",
    uploadedAttachments: "已添加 {count} 个附件",
    clearAttachments: "清空",
    addAttachments: "添加附件",
    removeAttachment: "移除",
    sendMessage: "发送消息",
    stopGenerating: "停止生成",
    generatingResponse: "正在生成回复",
    positiveFeedback: "有帮助",
    negativeFeedback: "没有帮助",
    filePreview: "文件预览",
    closeFilePreview: "关闭文件预览",
    openFile: "打开文件",
    previewUnavailable: "此文件类型暂不支持预览。",
    relationCandidates: "请选择关系记录",
    relationNoResults: "没有找到匹配的记录",
    relationSelectionExpired: "当前表单已变化，请重新查询候选记录",
    confirmRelationSelection: "确认选择",
    selectedRelationCount: "已选择 {count} 项"
  };
  const defaultIcons = {
    assistant: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "text-[10px] font-semibold leading-none", children: "AI" }),
    user: /* @__PURE__ */ jsxRuntimeExports.jsx(User, { className: "size-4" }),
    send: /* @__PURE__ */ jsxRuntimeExports.jsx(Send, { className: "size-4" }),
    stop: /* @__PURE__ */ jsxRuntimeExports.jsx(Square, { className: "size-4 fill-current" }),
    upload: /* @__PURE__ */ jsxRuntimeExports.jsx(Paperclip, { className: "size-4" }),
    copy: /* @__PURE__ */ jsxRuntimeExports.jsx(Copy, { className: "size-3.5" }),
    complete: /* @__PURE__ */ jsxRuntimeExports.jsx(Check, { className: "size-3.5" }),
    regenerate: /* @__PURE__ */ jsxRuntimeExports.jsx(RefreshCcw, { className: "size-3.5" }),
    activity: /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "agui-activity-dot" })
  };
  function mergeLabels(labels) {
    return { ...defaultLabels, ...labels };
  }
  function mergeIcons(icons) {
    return { ...defaultIcons, ...icons };
  }
  function observeInteraction(callback) {
    if (!callback) return;
    try {
      callback();
    } catch (error) {
      console.error("AG-UI 交互监听器执行失败", error);
    }
  }
  var reactDomExports = requireReactDom();
  function r(e) {
    var t, f, n = "";
    if ("string" == typeof e || "number" == typeof e) n += e;
    else if ("object" == typeof e) if (Array.isArray(e)) {
      var o = e.length;
      for (t = 0; t < o; t++) e[t] && (f = r(e[t])) && (n && (n += " "), n += f);
    } else for (f in e) e[f] && (n && (n += " "), n += f);
    return n;
  }
  function clsx() {
    for (var e, t, f = 0, n = "", o = arguments.length; f < o; f++) (e = arguments[f]) && (t = r(e)) && (n && (n += " "), n += t);
    return n;
  }
  const concatArrays = (array1, array2) => {
    const combinedArray = new Array(array1.length + array2.length);
    for (let i = 0; i < array1.length; i++) {
      combinedArray[i] = array1[i];
    }
    for (let i = 0; i < array2.length; i++) {
      combinedArray[array1.length + i] = array2[i];
    }
    return combinedArray;
  };
  const createClassValidatorObject = (classGroupId, validator) => ({
    classGroupId,
    validator
  });
  const createClassPartObject = (nextPart = /* @__PURE__ */ new Map(), validators = null, classGroupId) => ({
    nextPart,
    validators,
    classGroupId
  });
  const CLASS_PART_SEPARATOR = "-";
  const EMPTY_CONFLICTS = [];
  const ARBITRARY_PROPERTY_PREFIX = "arbitrary..";
  const createClassGroupUtils = (config) => {
    const classMap = createClassMap(config);
    const {
      conflictingClassGroups,
      conflictingClassGroupModifiers
    } = config;
    const getClassGroupId = (className) => {
      if (className.startsWith("[") && className.endsWith("]")) {
        return getGroupIdForArbitraryProperty(className);
      }
      const classParts = className.split(CLASS_PART_SEPARATOR);
      const startIndex = classParts[0] === "" && classParts.length > 1 ? 1 : 0;
      return getGroupRecursive(classParts, startIndex, classMap);
    };
    const getConflictingClassGroupIds = (classGroupId, hasPostfixModifier) => {
      if (hasPostfixModifier) {
        const modifierConflicts = conflictingClassGroupModifiers[classGroupId];
        const baseConflicts = conflictingClassGroups[classGroupId];
        if (modifierConflicts) {
          if (baseConflicts) {
            return concatArrays(baseConflicts, modifierConflicts);
          }
          return modifierConflicts;
        }
        return baseConflicts || EMPTY_CONFLICTS;
      }
      return conflictingClassGroups[classGroupId] || EMPTY_CONFLICTS;
    };
    return {
      getClassGroupId,
      getConflictingClassGroupIds
    };
  };
  const getGroupRecursive = (classParts, startIndex, classPartObject) => {
    const classPathsLength = classParts.length - startIndex;
    if (classPathsLength === 0) {
      return classPartObject.classGroupId;
    }
    const currentClassPart = classParts[startIndex];
    const nextClassPartObject = classPartObject.nextPart.get(currentClassPart);
    if (nextClassPartObject) {
      const result = getGroupRecursive(classParts, startIndex + 1, nextClassPartObject);
      if (result) return result;
    }
    const validators = classPartObject.validators;
    if (validators === null) {
      return void 0;
    }
    const classRest = startIndex === 0 ? classParts.join(CLASS_PART_SEPARATOR) : classParts.slice(startIndex).join(CLASS_PART_SEPARATOR);
    const validatorsLength = validators.length;
    for (let i = 0; i < validatorsLength; i++) {
      const validatorObj = validators[i];
      if (validatorObj.validator(classRest)) {
        return validatorObj.classGroupId;
      }
    }
    return void 0;
  };
  const getGroupIdForArbitraryProperty = (className) => className.slice(1, -1).indexOf(":") === -1 ? void 0 : (() => {
    const content2 = className.slice(1, -1);
    const colonIndex = content2.indexOf(":");
    const property = content2.slice(0, colonIndex);
    return property ? ARBITRARY_PROPERTY_PREFIX + property : void 0;
  })();
  const createClassMap = (config) => {
    const {
      theme,
      classGroups
    } = config;
    return processClassGroups(classGroups, theme);
  };
  const processClassGroups = (classGroups, theme) => {
    const classMap = createClassPartObject();
    for (const classGroupId in classGroups) {
      const group = classGroups[classGroupId];
      processClassesRecursively(group, classMap, classGroupId, theme);
    }
    return classMap;
  };
  const processClassesRecursively = (classGroup, classPartObject, classGroupId, theme) => {
    const len = classGroup.length;
    for (let i = 0; i < len; i++) {
      const classDefinition = classGroup[i];
      processClassDefinition(classDefinition, classPartObject, classGroupId, theme);
    }
  };
  const processClassDefinition = (classDefinition, classPartObject, classGroupId, theme) => {
    if (typeof classDefinition === "string") {
      processStringDefinition(classDefinition, classPartObject, classGroupId);
      return;
    }
    if (typeof classDefinition === "function") {
      processFunctionDefinition(classDefinition, classPartObject, classGroupId, theme);
      return;
    }
    processObjectDefinition(classDefinition, classPartObject, classGroupId, theme);
  };
  const processStringDefinition = (classDefinition, classPartObject, classGroupId) => {
    const classPartObjectToEdit = classDefinition === "" ? classPartObject : getPart(classPartObject, classDefinition);
    classPartObjectToEdit.classGroupId = classGroupId;
  };
  const processFunctionDefinition = (classDefinition, classPartObject, classGroupId, theme) => {
    if (isThemeGetter(classDefinition)) {
      processClassesRecursively(classDefinition(theme), classPartObject, classGroupId, theme);
      return;
    }
    if (classPartObject.validators === null) {
      classPartObject.validators = [];
    }
    classPartObject.validators.push(createClassValidatorObject(classGroupId, classDefinition));
  };
  const processObjectDefinition = (classDefinition, classPartObject, classGroupId, theme) => {
    const entries = Object.entries(classDefinition);
    const len = entries.length;
    for (let i = 0; i < len; i++) {
      const [key, value] = entries[i];
      processClassesRecursively(value, getPart(classPartObject, key), classGroupId, theme);
    }
  };
  const getPart = (classPartObject, path2) => {
    let current = classPartObject;
    const parts = path2.split(CLASS_PART_SEPARATOR);
    const len = parts.length;
    for (let i = 0; i < len; i++) {
      const part = parts[i];
      let next = current.nextPart.get(part);
      if (!next) {
        next = createClassPartObject();
        current.nextPart.set(part, next);
      }
      current = next;
    }
    return current;
  };
  const isThemeGetter = (func) => "isThemeGetter" in func && func.isThemeGetter === true;
  const createLruCache = (maxCacheSize) => {
    if (maxCacheSize < 1) {
      return {
        get: () => void 0,
        set: () => {
        }
      };
    }
    let cacheSize = 0;
    let cache = /* @__PURE__ */ Object.create(null);
    let previousCache = /* @__PURE__ */ Object.create(null);
    const update = (key, value) => {
      cache[key] = value;
      cacheSize++;
      if (cacheSize > maxCacheSize) {
        cacheSize = 0;
        previousCache = cache;
        cache = /* @__PURE__ */ Object.create(null);
      }
    };
    return {
      get(key) {
        let value = cache[key];
        if (value !== void 0) {
          return value;
        }
        if ((value = previousCache[key]) !== void 0) {
          update(key, value);
          return value;
        }
      },
      set(key, value) {
        if (key in cache) {
          cache[key] = value;
        } else {
          update(key, value);
        }
      }
    };
  };
  const IMPORTANT_MODIFIER = "!";
  const MODIFIER_SEPARATOR = ":";
  const EMPTY_MODIFIERS = [];
  const createResultObject = (modifiers, hasImportantModifier, baseClassName, maybePostfixModifierPosition, isExternal) => ({
    modifiers,
    hasImportantModifier,
    baseClassName,
    maybePostfixModifierPosition,
    isExternal
  });
  const createParseClassName = (config) => {
    const {
      prefix,
      experimentalParseClassName
    } = config;
    let parseClassName = (className) => {
      const modifiers = [];
      let bracketDepth = 0;
      let parenDepth = 0;
      let modifierStart = 0;
      let postfixModifierPosition;
      const len = className.length;
      for (let index2 = 0; index2 < len; index2++) {
        const currentCharacter = className[index2];
        if (bracketDepth === 0 && parenDepth === 0) {
          if (currentCharacter === MODIFIER_SEPARATOR) {
            modifiers.push(className.slice(modifierStart, index2));
            modifierStart = index2 + 1;
            continue;
          }
          if (currentCharacter === "/") {
            postfixModifierPosition = index2;
            continue;
          }
        }
        if (currentCharacter === "[") bracketDepth++;
        else if (currentCharacter === "]") bracketDepth--;
        else if (currentCharacter === "(") parenDepth++;
        else if (currentCharacter === ")") parenDepth--;
      }
      const baseClassNameWithImportantModifier = modifiers.length === 0 ? className : className.slice(modifierStart);
      let baseClassName = baseClassNameWithImportantModifier;
      let hasImportantModifier = false;
      if (baseClassNameWithImportantModifier.endsWith(IMPORTANT_MODIFIER)) {
        baseClassName = baseClassNameWithImportantModifier.slice(0, -1);
        hasImportantModifier = true;
      } else if (
        /**
         * In Tailwind CSS v3 the important modifier was at the start of the base class name. This is still supported for legacy reasons.
         * @see https://github.com/dcastil/tailwind-merge/issues/513#issuecomment-2614029864
         */
        baseClassNameWithImportantModifier.startsWith(IMPORTANT_MODIFIER)
      ) {
        baseClassName = baseClassNameWithImportantModifier.slice(1);
        hasImportantModifier = true;
      }
      const maybePostfixModifierPosition = postfixModifierPosition && postfixModifierPosition > modifierStart ? postfixModifierPosition - modifierStart : void 0;
      return createResultObject(modifiers, hasImportantModifier, baseClassName, maybePostfixModifierPosition);
    };
    if (prefix) {
      const fullPrefix = prefix + MODIFIER_SEPARATOR;
      const parseClassNameOriginal = parseClassName;
      parseClassName = (className) => className.startsWith(fullPrefix) ? parseClassNameOriginal(className.slice(fullPrefix.length)) : createResultObject(EMPTY_MODIFIERS, false, className, void 0, true);
    }
    if (experimentalParseClassName) {
      const parseClassNameOriginal = parseClassName;
      parseClassName = (className) => experimentalParseClassName({
        className,
        parseClassName: parseClassNameOriginal
      });
    }
    return parseClassName;
  };
  const createSortModifiers = (config) => {
    const modifierWeights = /* @__PURE__ */ new Map();
    config.orderSensitiveModifiers.forEach((mod, index2) => {
      modifierWeights.set(mod, 1e6 + index2);
    });
    return (modifiers) => {
      const result = [];
      let currentSegment = [];
      for (let i = 0; i < modifiers.length; i++) {
        const modifier = modifiers[i];
        const isArbitrary = modifier[0] === "[";
        const isOrderSensitive = modifierWeights.has(modifier);
        if (isArbitrary || isOrderSensitive) {
          if (currentSegment.length > 0) {
            currentSegment.sort();
            result.push(...currentSegment);
            currentSegment = [];
          }
          result.push(modifier);
        } else {
          currentSegment.push(modifier);
        }
      }
      if (currentSegment.length > 0) {
        currentSegment.sort();
        result.push(...currentSegment);
      }
      return result;
    };
  };
  const createConfigUtils = (config) => ({
    cache: createLruCache(config.cacheSize),
    parseClassName: createParseClassName(config),
    sortModifiers: createSortModifiers(config),
    postfixLookupClassGroupIds: createPostfixLookupClassGroupIds(config),
    ...createClassGroupUtils(config)
  });
  const createPostfixLookupClassGroupIds = (config) => {
    const lookup = /* @__PURE__ */ Object.create(null);
    const classGroupIds = config.postfixLookupClassGroups;
    if (classGroupIds) {
      for (let i = 0; i < classGroupIds.length; i++) {
        lookup[classGroupIds[i]] = true;
      }
    }
    return lookup;
  };
  const SPLIT_CLASSES_REGEX = /\s+/;
  const mergeClassList = (classList, configUtils) => {
    const {
      parseClassName,
      getClassGroupId,
      getConflictingClassGroupIds,
      sortModifiers,
      postfixLookupClassGroupIds
    } = configUtils;
    const classGroupsInConflict = [];
    const classNames = classList.trim().split(SPLIT_CLASSES_REGEX);
    let result = "";
    for (let index2 = classNames.length - 1; index2 >= 0; index2 -= 1) {
      const originalClassName = classNames[index2];
      const {
        isExternal,
        modifiers,
        hasImportantModifier,
        baseClassName,
        maybePostfixModifierPosition
      } = parseClassName(originalClassName);
      if (isExternal) {
        result = originalClassName + (result.length > 0 ? " " + result : result);
        continue;
      }
      let hasPostfixModifier = !!maybePostfixModifierPosition;
      let classGroupId;
      if (hasPostfixModifier) {
        const baseClassNameWithoutPostfix = baseClassName.substring(0, maybePostfixModifierPosition);
        classGroupId = getClassGroupId(baseClassNameWithoutPostfix);
        const classGroupIdWithPostfix = classGroupId && postfixLookupClassGroupIds[classGroupId] ? getClassGroupId(baseClassName) : void 0;
        if (classGroupIdWithPostfix && classGroupIdWithPostfix !== classGroupId) {
          classGroupId = classGroupIdWithPostfix;
          hasPostfixModifier = false;
        }
      } else {
        classGroupId = getClassGroupId(baseClassName);
      }
      if (!classGroupId) {
        if (!hasPostfixModifier) {
          result = originalClassName + (result.length > 0 ? " " + result : result);
          continue;
        }
        classGroupId = getClassGroupId(baseClassName);
        if (!classGroupId) {
          result = originalClassName + (result.length > 0 ? " " + result : result);
          continue;
        }
        hasPostfixModifier = false;
      }
      const variantModifier = modifiers.length === 0 ? "" : modifiers.length === 1 ? modifiers[0] : sortModifiers(modifiers).join(":");
      const modifierId = hasImportantModifier ? variantModifier + IMPORTANT_MODIFIER : variantModifier;
      const classId = modifierId + classGroupId;
      if (classGroupsInConflict.indexOf(classId) > -1) {
        continue;
      }
      classGroupsInConflict.push(classId);
      const conflictGroups = getConflictingClassGroupIds(classGroupId, hasPostfixModifier);
      for (let i = 0; i < conflictGroups.length; ++i) {
        const group = conflictGroups[i];
        classGroupsInConflict.push(modifierId + group);
      }
      result = originalClassName + (result.length > 0 ? " " + result : result);
    }
    return result;
  };
  const twJoin = (...classLists) => {
    let index2 = 0;
    let argument;
    let resolvedValue;
    let string2 = "";
    while (index2 < classLists.length) {
      if (argument = classLists[index2++]) {
        if (resolvedValue = toValue(argument)) {
          string2 && (string2 += " ");
          string2 += resolvedValue;
        }
      }
    }
    return string2;
  };
  const toValue = (mix) => {
    if (typeof mix === "string") {
      return mix;
    }
    let resolvedValue;
    let string2 = "";
    for (let k = 0; k < mix.length; k++) {
      if (mix[k]) {
        if (resolvedValue = toValue(mix[k])) {
          string2 && (string2 += " ");
          string2 += resolvedValue;
        }
      }
    }
    return string2;
  };
  const createTailwindMerge = (createConfigFirst, ...createConfigRest) => {
    let configUtils;
    let cacheGet;
    let cacheSet;
    let functionToCall;
    const initTailwindMerge = (classList) => {
      const config = createConfigRest.reduce((previousConfig, createConfigCurrent) => createConfigCurrent(previousConfig), createConfigFirst());
      configUtils = createConfigUtils(config);
      cacheGet = configUtils.cache.get;
      cacheSet = configUtils.cache.set;
      functionToCall = tailwindMerge;
      return tailwindMerge(classList);
    };
    const tailwindMerge = (classList) => {
      const cachedResult = cacheGet(classList);
      if (cachedResult) {
        return cachedResult;
      }
      const result = mergeClassList(classList, configUtils);
      cacheSet(classList, result);
      return result;
    };
    functionToCall = initTailwindMerge;
    return (...args) => functionToCall(twJoin(...args));
  };
  const fallbackThemeArr = [];
  const fromTheme = (key) => {
    const themeGetter = (theme) => theme[key] || fallbackThemeArr;
    themeGetter.isThemeGetter = true;
    return themeGetter;
  };
  const arbitraryValueRegex = /^\[(?:(\w[\w-]*):)?(.+)\]$/i;
  const arbitraryVariableRegex = /^\((?:(\w[\w-]*):)?(.+)\)$/i;
  const fractionRegex = /^\d+(?:\.\d+)?\/\d+(?:\.\d+)?$/;
  const tshirtUnitRegex = /^(\d+(\.\d+)?)?(xs|sm|md|lg|xl)$/;
  const lengthUnitRegex = /\d+(%|px|r?em|[sdl]?v([hwib]|min|max)|pt|pc|in|cm|mm|cap|ch|ex|r?lh|cq(w|h|i|b|min|max))|\b(calc|min|max|clamp)\(.+\)|^0$/;
  const colorFunctionRegex = /^(rgba?|hsla?|hwb|(ok)?(lab|lch)|color-mix)\(.+\)$/;
  const shadowRegex = /^(inset_)?-?((\d+)?\.?(\d+)[a-z]+|0)_-?((\d+)?\.?(\d+)[a-z]+|0)/;
  const imageRegex = /^(url|image|image-set|cross-fade|element|(repeating-)?(linear|radial|conic)-gradient)\(.+\)$/;
  const isFraction = (value) => fractionRegex.test(value);
  const isNumber = (value) => !!value && !Number.isNaN(Number(value));
  const isInteger = (value) => !!value && Number.isInteger(Number(value));
  const isPercent = (value) => value.endsWith("%") && isNumber(value.slice(0, -1));
  const isTshirtSize = (value) => tshirtUnitRegex.test(value);
  const isAny = () => true;
  const isLengthOnly = (value) => (
    // `colorFunctionRegex` check is necessary because color functions can have percentages in them which which would be incorrectly classified as lengths.
    // For example, `hsl(0 0% 0%)` would be classified as a length without this check.
    // I could also use lookbehind assertion in `lengthUnitRegex` but that isn't supported widely enough.
    lengthUnitRegex.test(value) && !colorFunctionRegex.test(value)
  );
  const isNever = () => false;
  const isShadow = (value) => shadowRegex.test(value);
  const isImage = (value) => imageRegex.test(value);
  const isAnyNonArbitrary = (value) => !isArbitraryValue(value) && !isArbitraryVariable(value);
  const isNamedContainerQuery = (value) => value.startsWith("@container") && (value[10] === "/" && value[11] !== void 0 || value[11] === "s" && value[16] !== void 0 && value.startsWith("-size/", 10) || value[11] === "n" && value[18] !== void 0 && value.startsWith("-normal/", 10));
  const isArbitrarySize = (value) => getIsArbitraryValue(value, isLabelSize, isNever);
  const isArbitraryValue = (value) => arbitraryValueRegex.test(value);
  const isArbitraryLength = (value) => getIsArbitraryValue(value, isLabelLength, isLengthOnly);
  const isArbitraryNumber = (value) => getIsArbitraryValue(value, isLabelNumber, isNumber);
  const isArbitraryWeight = (value) => getIsArbitraryValue(value, isLabelWeight, isAny);
  const isArbitraryFamilyName = (value) => getIsArbitraryValue(value, isLabelFamilyName, isNever);
  const isArbitraryPosition = (value) => getIsArbitraryValue(value, isLabelPosition, isNever);
  const isArbitraryImage = (value) => getIsArbitraryValue(value, isLabelImage, isImage);
  const isArbitraryShadow = (value) => getIsArbitraryValue(value, isLabelShadow, isShadow);
  const isArbitraryVariable = (value) => arbitraryVariableRegex.test(value);
  const isArbitraryVariableLength = (value) => getIsArbitraryVariable(value, isLabelLength);
  const isArbitraryVariableFamilyName = (value) => getIsArbitraryVariable(value, isLabelFamilyName);
  const isArbitraryVariablePosition = (value) => getIsArbitraryVariable(value, isLabelPosition);
  const isArbitraryVariableSize = (value) => getIsArbitraryVariable(value, isLabelSize);
  const isArbitraryVariableImage = (value) => getIsArbitraryVariable(value, isLabelImage);
  const isArbitraryVariableShadow = (value) => getIsArbitraryVariable(value, isLabelShadow, true);
  const isArbitraryVariableWeight = (value) => getIsArbitraryVariable(value, isLabelWeight, true);
  const getIsArbitraryValue = (value, testLabel, testValue) => {
    const result = arbitraryValueRegex.exec(value);
    if (result) {
      if (result[1]) {
        return testLabel(result[1]);
      }
      return testValue(result[2]);
    }
    return false;
  };
  const getIsArbitraryVariable = (value, testLabel, shouldMatchNoLabel = false) => {
    const result = arbitraryVariableRegex.exec(value);
    if (result) {
      if (result[1]) {
        return testLabel(result[1]);
      }
      return shouldMatchNoLabel;
    }
    return false;
  };
  const isLabelPosition = (label) => label === "position" || label === "percentage";
  const isLabelImage = (label) => label === "image" || label === "url";
  const isLabelSize = (label) => label === "length" || label === "size" || label === "bg-size";
  const isLabelLength = (label) => label === "length";
  const isLabelNumber = (label) => label === "number";
  const isLabelFamilyName = (label) => label === "family-name";
  const isLabelWeight = (label) => label === "number" || label === "weight";
  const isLabelShadow = (label) => label === "shadow";
  const getDefaultConfig = () => {
    const themeColor = fromTheme("color");
    const themeFont = fromTheme("font");
    const themeText = fromTheme("text");
    const themeFontWeight = fromTheme("font-weight");
    const themeTracking = fromTheme("tracking");
    const themeLeading = fromTheme("leading");
    const themeBreakpoint = fromTheme("breakpoint");
    const themeContainer = fromTheme("container");
    const themeSpacing = fromTheme("spacing");
    const themeRadius = fromTheme("radius");
    const themeShadow = fromTheme("shadow");
    const themeInsetShadow = fromTheme("inset-shadow");
    const themeTextShadow = fromTheme("text-shadow");
    const themeDropShadow = fromTheme("drop-shadow");
    const themeBlur = fromTheme("blur");
    const themePerspective = fromTheme("perspective");
    const themeAspect = fromTheme("aspect");
    const themeEase = fromTheme("ease");
    const themeAnimate = fromTheme("animate");
    const scaleBreak = () => ["auto", "avoid", "all", "avoid-page", "page", "left", "right", "column"];
    const scalePosition = () => [
      "center",
      "top",
      "bottom",
      "left",
      "right",
      "top-left",
      // Deprecated since Tailwind CSS v4.1.0, see https://github.com/tailwindlabs/tailwindcss/pull/17378
      "left-top",
      "top-right",
      // Deprecated since Tailwind CSS v4.1.0, see https://github.com/tailwindlabs/tailwindcss/pull/17378
      "right-top",
      "bottom-right",
      // Deprecated since Tailwind CSS v4.1.0, see https://github.com/tailwindlabs/tailwindcss/pull/17378
      "right-bottom",
      "bottom-left",
      // Deprecated since Tailwind CSS v4.1.0, see https://github.com/tailwindlabs/tailwindcss/pull/17378
      "left-bottom"
    ];
    const scalePositionWithArbitrary = () => [...scalePosition(), isArbitraryVariable, isArbitraryValue];
    const scaleOverflow = () => ["auto", "hidden", "clip", "visible", "scroll"];
    const scaleOverscroll = () => ["auto", "contain", "none"];
    const scaleUnambiguousSpacing = () => [isArbitraryVariable, isArbitraryValue, themeSpacing];
    const scaleInset = () => [isFraction, "full", "auto", ...scaleUnambiguousSpacing()];
    const scaleGridTemplateColsRows = () => [isInteger, "none", "subgrid", isArbitraryVariable, isArbitraryValue];
    const scaleGridColRowStartAndEnd = () => ["auto", {
      span: ["full", isInteger, isArbitraryVariable, isArbitraryValue]
    }, isInteger, isArbitraryVariable, isArbitraryValue];
    const scaleGridColRowStartOrEnd = () => [isInteger, "auto", isArbitraryVariable, isArbitraryValue];
    const scaleGridAutoColsRows = () => ["auto", "min", "max", "fr", isArbitraryVariable, isArbitraryValue];
    const scaleAlignPrimaryAxis = () => ["start", "end", "center", "between", "around", "evenly", "stretch", "baseline", "center-safe", "end-safe"];
    const scaleAlignSecondaryAxis = () => ["start", "end", "center", "stretch", "center-safe", "end-safe"];
    const scaleMargin = () => ["auto", ...scaleUnambiguousSpacing()];
    const scaleSizing = () => [isFraction, "auto", "full", "dvw", "dvh", "lvw", "lvh", "svw", "svh", "min", "max", "fit", ...scaleUnambiguousSpacing()];
    const scaleSizingInline = () => [isFraction, "screen", "full", "dvw", "lvw", "svw", "min", "max", "fit", ...scaleUnambiguousSpacing()];
    const scaleSizingBlock = () => [isFraction, "screen", "full", "lh", "dvh", "lvh", "svh", "min", "max", "fit", ...scaleUnambiguousSpacing()];
    const scaleColor = () => [themeColor, isArbitraryVariable, isArbitraryValue];
    const scaleBgPosition = () => [...scalePosition(), isArbitraryVariablePosition, isArbitraryPosition, {
      position: [isArbitraryVariable, isArbitraryValue]
    }];
    const scaleBgRepeat = () => ["no-repeat", {
      repeat: ["", "x", "y", "space", "round"]
    }];
    const scaleBgSize = () => ["auto", "cover", "contain", isArbitraryVariableSize, isArbitrarySize, {
      size: [isArbitraryVariable, isArbitraryValue]
    }];
    const scaleGradientStopPosition = () => [isPercent, isArbitraryVariableLength, isArbitraryLength];
    const scaleRadius = () => [
      // Deprecated since Tailwind CSS v4.0.0
      "",
      "none",
      "full",
      themeRadius,
      isArbitraryVariable,
      isArbitraryValue
    ];
    const scaleBorderWidth = () => ["", isNumber, isArbitraryVariableLength, isArbitraryLength];
    const scaleLineStyle = () => ["solid", "dashed", "dotted", "double"];
    const scaleBlendMode = () => ["normal", "multiply", "screen", "overlay", "darken", "lighten", "color-dodge", "color-burn", "hard-light", "soft-light", "difference", "exclusion", "hue", "saturation", "color", "luminosity"];
    const scaleMaskImagePosition = () => [isNumber, isPercent, isArbitraryVariablePosition, isArbitraryPosition];
    const scaleBlur = () => [
      // Deprecated since Tailwind CSS v4.0.0
      "",
      "none",
      themeBlur,
      isArbitraryVariable,
      isArbitraryValue
    ];
    const scaleRotate = () => ["none", isNumber, isArbitraryVariable, isArbitraryValue];
    const scaleScale = () => ["none", isNumber, isArbitraryVariable, isArbitraryValue];
    const scaleSkew = () => [isNumber, isArbitraryVariable, isArbitraryValue];
    const scaleTranslate = () => [isFraction, "full", ...scaleUnambiguousSpacing()];
    return {
      cacheSize: 500,
      theme: {
        animate: ["spin", "ping", "pulse", "bounce"],
        aspect: ["video"],
        blur: [isTshirtSize],
        breakpoint: [isTshirtSize],
        color: [isAny],
        container: [isTshirtSize],
        "drop-shadow": [isTshirtSize],
        ease: ["in", "out", "in-out"],
        font: [isAnyNonArbitrary],
        "font-weight": ["thin", "extralight", "light", "normal", "medium", "semibold", "bold", "extrabold", "black"],
        "inset-shadow": [isTshirtSize],
        leading: ["none", "tight", "snug", "normal", "relaxed", "loose"],
        perspective: ["dramatic", "near", "normal", "midrange", "distant", "none"],
        radius: [isTshirtSize],
        shadow: [isTshirtSize],
        spacing: ["px", isNumber],
        text: [isTshirtSize],
        "text-shadow": [isTshirtSize],
        tracking: ["tighter", "tight", "normal", "wide", "wider", "widest"]
      },
      classGroups: {
        // --------------
        // --- Layout ---
        // --------------
        /**
         * Aspect Ratio
         * @see https://tailwindcss.com/docs/aspect-ratio
         */
        aspect: [{
          aspect: ["auto", "square", isFraction, isArbitraryValue, isArbitraryVariable, themeAspect]
        }],
        /**
         * Container
         * @see https://tailwindcss.com/docs/container
         * @deprecated since Tailwind CSS v4.0.0
         */
        container: ["container"],
        /**
         * Container Type
         * @see https://tailwindcss.com/docs/responsive-design#container-queries
         */
        "container-type": [{
          "@container": ["", "normal", "size", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Container Name
         * @see https://tailwindcss.com/docs/responsive-design#named-containers
         */
        "container-named": [isNamedContainerQuery],
        /**
         * Columns
         * @see https://tailwindcss.com/docs/columns
         */
        columns: [{
          columns: [isNumber, isArbitraryValue, isArbitraryVariable, themeContainer]
        }],
        /**
         * Break After
         * @see https://tailwindcss.com/docs/break-after
         */
        "break-after": [{
          "break-after": scaleBreak()
        }],
        /**
         * Break Before
         * @see https://tailwindcss.com/docs/break-before
         */
        "break-before": [{
          "break-before": scaleBreak()
        }],
        /**
         * Break Inside
         * @see https://tailwindcss.com/docs/break-inside
         */
        "break-inside": [{
          "break-inside": ["auto", "avoid", "avoid-page", "avoid-column"]
        }],
        /**
         * Box Decoration Break
         * @see https://tailwindcss.com/docs/box-decoration-break
         */
        "box-decoration": [{
          "box-decoration": ["slice", "clone"]
        }],
        /**
         * Box Sizing
         * @see https://tailwindcss.com/docs/box-sizing
         */
        box: [{
          box: ["border", "content"]
        }],
        /**
         * Display
         * @see https://tailwindcss.com/docs/display
         */
        display: ["block", "inline-block", "inline", "flex", "inline-flex", "table", "inline-table", "table-caption", "table-cell", "table-column", "table-column-group", "table-footer-group", "table-header-group", "table-row-group", "table-row", "flow-root", "grid", "inline-grid", "contents", "list-item", "hidden"],
        /**
         * Screen Reader Only
         * @see https://tailwindcss.com/docs/display#screen-reader-only
         */
        sr: ["sr-only", "not-sr-only"],
        /**
         * Floats
         * @see https://tailwindcss.com/docs/float
         */
        float: [{
          float: ["right", "left", "none", "start", "end"]
        }],
        /**
         * Clear
         * @see https://tailwindcss.com/docs/clear
         */
        clear: [{
          clear: ["left", "right", "both", "none", "start", "end"]
        }],
        /**
         * Isolation
         * @see https://tailwindcss.com/docs/isolation
         */
        isolation: ["isolate", "isolation-auto"],
        /**
         * Object Fit
         * @see https://tailwindcss.com/docs/object-fit
         */
        "object-fit": [{
          object: ["contain", "cover", "fill", "none", "scale-down"]
        }],
        /**
         * Object Position
         * @see https://tailwindcss.com/docs/object-position
         */
        "object-position": [{
          object: scalePositionWithArbitrary()
        }],
        /**
         * Overflow
         * @see https://tailwindcss.com/docs/overflow
         */
        overflow: [{
          overflow: scaleOverflow()
        }],
        /**
         * Overflow X
         * @see https://tailwindcss.com/docs/overflow
         */
        "overflow-x": [{
          "overflow-x": scaleOverflow()
        }],
        /**
         * Overflow Y
         * @see https://tailwindcss.com/docs/overflow
         */
        "overflow-y": [{
          "overflow-y": scaleOverflow()
        }],
        /**
         * Overscroll Behavior
         * @see https://tailwindcss.com/docs/overscroll-behavior
         */
        overscroll: [{
          overscroll: scaleOverscroll()
        }],
        /**
         * Overscroll Behavior X
         * @see https://tailwindcss.com/docs/overscroll-behavior
         */
        "overscroll-x": [{
          "overscroll-x": scaleOverscroll()
        }],
        /**
         * Overscroll Behavior Y
         * @see https://tailwindcss.com/docs/overscroll-behavior
         */
        "overscroll-y": [{
          "overscroll-y": scaleOverscroll()
        }],
        /**
         * Position
         * @see https://tailwindcss.com/docs/position
         */
        position: ["static", "fixed", "absolute", "relative", "sticky"],
        /**
         * Inset
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        inset: [{
          inset: scaleInset()
        }],
        /**
         * Inset Inline
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        "inset-x": [{
          "inset-x": scaleInset()
        }],
        /**
         * Inset Block
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        "inset-y": [{
          "inset-y": scaleInset()
        }],
        /**
         * Inset Inline Start
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         * @todo class group will be renamed to `inset-s` in next major release
         */
        start: [{
          "inset-s": scaleInset(),
          /**
           * @deprecated since Tailwind CSS v4.2.0 in favor of `inset-s-*` utilities.
           * @see https://github.com/tailwindlabs/tailwindcss/pull/19613
           */
          start: scaleInset()
        }],
        /**
         * Inset Inline End
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         * @todo class group will be renamed to `inset-e` in next major release
         */
        end: [{
          "inset-e": scaleInset(),
          /**
           * @deprecated since Tailwind CSS v4.2.0 in favor of `inset-e-*` utilities.
           * @see https://github.com/tailwindlabs/tailwindcss/pull/19613
           */
          end: scaleInset()
        }],
        /**
         * Inset Block Start
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        "inset-bs": [{
          "inset-bs": scaleInset()
        }],
        /**
         * Inset Block End
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        "inset-be": [{
          "inset-be": scaleInset()
        }],
        /**
         * Top
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        top: [{
          top: scaleInset()
        }],
        /**
         * Right
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        right: [{
          right: scaleInset()
        }],
        /**
         * Bottom
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        bottom: [{
          bottom: scaleInset()
        }],
        /**
         * Left
         * @see https://tailwindcss.com/docs/top-right-bottom-left
         */
        left: [{
          left: scaleInset()
        }],
        /**
         * Visibility
         * @see https://tailwindcss.com/docs/visibility
         */
        visibility: ["visible", "invisible", "collapse"],
        /**
         * Z-Index
         * @see https://tailwindcss.com/docs/z-index
         */
        z: [{
          z: [isInteger, "auto", isArbitraryVariable, isArbitraryValue]
        }],
        // ------------------------
        // --- Flexbox and Grid ---
        // ------------------------
        /**
         * Flex Basis
         * @see https://tailwindcss.com/docs/flex-basis
         */
        basis: [{
          basis: [isFraction, "full", "auto", themeContainer, ...scaleUnambiguousSpacing()]
        }],
        /**
         * Flex Direction
         * @see https://tailwindcss.com/docs/flex-direction
         */
        "flex-direction": [{
          flex: ["row", "row-reverse", "col", "col-reverse"]
        }],
        /**
         * Flex Wrap
         * @see https://tailwindcss.com/docs/flex-wrap
         */
        "flex-wrap": [{
          flex: ["nowrap", "wrap", "wrap-reverse"]
        }],
        /**
         * Flex
         * @see https://tailwindcss.com/docs/flex
         */
        flex: [{
          flex: [isNumber, isFraction, "auto", "initial", "none", isArbitraryValue]
        }],
        /**
         * Flex Grow
         * @see https://tailwindcss.com/docs/flex-grow
         */
        grow: [{
          grow: ["", isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Flex Shrink
         * @see https://tailwindcss.com/docs/flex-shrink
         */
        shrink: [{
          shrink: ["", isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Order
         * @see https://tailwindcss.com/docs/order
         */
        order: [{
          order: [isInteger, "first", "last", "none", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Grid Template Columns
         * @see https://tailwindcss.com/docs/grid-template-columns
         */
        "grid-cols": [{
          "grid-cols": scaleGridTemplateColsRows()
        }],
        /**
         * Grid Column Start / End
         * @see https://tailwindcss.com/docs/grid-column
         */
        "col-start-end": [{
          col: scaleGridColRowStartAndEnd()
        }],
        /**
         * Grid Column Start
         * @see https://tailwindcss.com/docs/grid-column
         */
        "col-start": [{
          "col-start": scaleGridColRowStartOrEnd()
        }],
        /**
         * Grid Column End
         * @see https://tailwindcss.com/docs/grid-column
         */
        "col-end": [{
          "col-end": scaleGridColRowStartOrEnd()
        }],
        /**
         * Grid Template Rows
         * @see https://tailwindcss.com/docs/grid-template-rows
         */
        "grid-rows": [{
          "grid-rows": scaleGridTemplateColsRows()
        }],
        /**
         * Grid Row Start / End
         * @see https://tailwindcss.com/docs/grid-row
         */
        "row-start-end": [{
          row: scaleGridColRowStartAndEnd()
        }],
        /**
         * Grid Row Start
         * @see https://tailwindcss.com/docs/grid-row
         */
        "row-start": [{
          "row-start": scaleGridColRowStartOrEnd()
        }],
        /**
         * Grid Row End
         * @see https://tailwindcss.com/docs/grid-row
         */
        "row-end": [{
          "row-end": scaleGridColRowStartOrEnd()
        }],
        /**
         * Grid Auto Flow
         * @see https://tailwindcss.com/docs/grid-auto-flow
         */
        "grid-flow": [{
          "grid-flow": ["row", "col", "dense", "row-dense", "col-dense"]
        }],
        /**
         * Grid Auto Columns
         * @see https://tailwindcss.com/docs/grid-auto-columns
         */
        "auto-cols": [{
          "auto-cols": scaleGridAutoColsRows()
        }],
        /**
         * Grid Auto Rows
         * @see https://tailwindcss.com/docs/grid-auto-rows
         */
        "auto-rows": [{
          "auto-rows": scaleGridAutoColsRows()
        }],
        /**
         * Gap
         * @see https://tailwindcss.com/docs/gap
         */
        gap: [{
          gap: scaleUnambiguousSpacing()
        }],
        /**
         * Gap X
         * @see https://tailwindcss.com/docs/gap
         */
        "gap-x": [{
          "gap-x": scaleUnambiguousSpacing()
        }],
        /**
         * Gap Y
         * @see https://tailwindcss.com/docs/gap
         */
        "gap-y": [{
          "gap-y": scaleUnambiguousSpacing()
        }],
        /**
         * Justify Content
         * @see https://tailwindcss.com/docs/justify-content
         */
        "justify-content": [{
          justify: [...scaleAlignPrimaryAxis(), "normal"]
        }],
        /**
         * Justify Items
         * @see https://tailwindcss.com/docs/justify-items
         */
        "justify-items": [{
          "justify-items": [...scaleAlignSecondaryAxis(), "normal"]
        }],
        /**
         * Justify Self
         * @see https://tailwindcss.com/docs/justify-self
         */
        "justify-self": [{
          "justify-self": ["auto", ...scaleAlignSecondaryAxis()]
        }],
        /**
         * Align Content
         * @see https://tailwindcss.com/docs/align-content
         */
        "align-content": [{
          content: ["normal", ...scaleAlignPrimaryAxis()]
        }],
        /**
         * Align Items
         * @see https://tailwindcss.com/docs/align-items
         */
        "align-items": [{
          items: [...scaleAlignSecondaryAxis(), {
            baseline: ["", "last"]
          }]
        }],
        /**
         * Align Self
         * @see https://tailwindcss.com/docs/align-self
         */
        "align-self": [{
          self: ["auto", ...scaleAlignSecondaryAxis(), {
            baseline: ["", "last"]
          }]
        }],
        /**
         * Place Content
         * @see https://tailwindcss.com/docs/place-content
         */
        "place-content": [{
          "place-content": scaleAlignPrimaryAxis()
        }],
        /**
         * Place Items
         * @see https://tailwindcss.com/docs/place-items
         */
        "place-items": [{
          "place-items": [...scaleAlignSecondaryAxis(), "baseline"]
        }],
        /**
         * Place Self
         * @see https://tailwindcss.com/docs/place-self
         */
        "place-self": [{
          "place-self": ["auto", ...scaleAlignSecondaryAxis()]
        }],
        // Spacing
        /**
         * Padding
         * @see https://tailwindcss.com/docs/padding
         */
        p: [{
          p: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Inline
         * @see https://tailwindcss.com/docs/padding
         */
        px: [{
          px: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Block
         * @see https://tailwindcss.com/docs/padding
         */
        py: [{
          py: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Inline Start
         * @see https://tailwindcss.com/docs/padding
         */
        ps: [{
          ps: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Inline End
         * @see https://tailwindcss.com/docs/padding
         */
        pe: [{
          pe: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Block Start
         * @see https://tailwindcss.com/docs/padding
         */
        pbs: [{
          pbs: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Block End
         * @see https://tailwindcss.com/docs/padding
         */
        pbe: [{
          pbe: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Top
         * @see https://tailwindcss.com/docs/padding
         */
        pt: [{
          pt: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Right
         * @see https://tailwindcss.com/docs/padding
         */
        pr: [{
          pr: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Bottom
         * @see https://tailwindcss.com/docs/padding
         */
        pb: [{
          pb: scaleUnambiguousSpacing()
        }],
        /**
         * Padding Left
         * @see https://tailwindcss.com/docs/padding
         */
        pl: [{
          pl: scaleUnambiguousSpacing()
        }],
        /**
         * Margin
         * @see https://tailwindcss.com/docs/margin
         */
        m: [{
          m: scaleMargin()
        }],
        /**
         * Margin Inline
         * @see https://tailwindcss.com/docs/margin
         */
        mx: [{
          mx: scaleMargin()
        }],
        /**
         * Margin Block
         * @see https://tailwindcss.com/docs/margin
         */
        my: [{
          my: scaleMargin()
        }],
        /**
         * Margin Inline Start
         * @see https://tailwindcss.com/docs/margin
         */
        ms: [{
          ms: scaleMargin()
        }],
        /**
         * Margin Inline End
         * @see https://tailwindcss.com/docs/margin
         */
        me: [{
          me: scaleMargin()
        }],
        /**
         * Margin Block Start
         * @see https://tailwindcss.com/docs/margin
         */
        mbs: [{
          mbs: scaleMargin()
        }],
        /**
         * Margin Block End
         * @see https://tailwindcss.com/docs/margin
         */
        mbe: [{
          mbe: scaleMargin()
        }],
        /**
         * Margin Top
         * @see https://tailwindcss.com/docs/margin
         */
        mt: [{
          mt: scaleMargin()
        }],
        /**
         * Margin Right
         * @see https://tailwindcss.com/docs/margin
         */
        mr: [{
          mr: scaleMargin()
        }],
        /**
         * Margin Bottom
         * @see https://tailwindcss.com/docs/margin
         */
        mb: [{
          mb: scaleMargin()
        }],
        /**
         * Margin Left
         * @see https://tailwindcss.com/docs/margin
         */
        ml: [{
          ml: scaleMargin()
        }],
        /**
         * Space Between X
         * @see https://tailwindcss.com/docs/margin#adding-space-between-children
         */
        "space-x": [{
          "space-x": scaleUnambiguousSpacing()
        }],
        /**
         * Space Between X Reverse
         * @see https://tailwindcss.com/docs/margin#adding-space-between-children
         */
        "space-x-reverse": ["space-x-reverse"],
        /**
         * Space Between Y
         * @see https://tailwindcss.com/docs/margin#adding-space-between-children
         */
        "space-y": [{
          "space-y": scaleUnambiguousSpacing()
        }],
        /**
         * Space Between Y Reverse
         * @see https://tailwindcss.com/docs/margin#adding-space-between-children
         */
        "space-y-reverse": ["space-y-reverse"],
        // --------------
        // --- Sizing ---
        // --------------
        /**
         * Size
         * @see https://tailwindcss.com/docs/width#setting-both-width-and-height
         */
        size: [{
          size: scaleSizing()
        }],
        /**
         * Inline Size
         * @see https://tailwindcss.com/docs/width
         */
        "inline-size": [{
          inline: ["auto", ...scaleSizingInline()]
        }],
        /**
         * Min-Inline Size
         * @see https://tailwindcss.com/docs/min-width
         */
        "min-inline-size": [{
          "min-inline": ["auto", ...scaleSizingInline()]
        }],
        /**
         * Max-Inline Size
         * @see https://tailwindcss.com/docs/max-width
         */
        "max-inline-size": [{
          "max-inline": ["none", ...scaleSizingInline()]
        }],
        /**
         * Block Size
         * @see https://tailwindcss.com/docs/height
         */
        "block-size": [{
          block: ["auto", ...scaleSizingBlock()]
        }],
        /**
         * Min-Block Size
         * @see https://tailwindcss.com/docs/min-height
         */
        "min-block-size": [{
          "min-block": ["auto", ...scaleSizingBlock()]
        }],
        /**
         * Max-Block Size
         * @see https://tailwindcss.com/docs/max-height
         */
        "max-block-size": [{
          "max-block": ["none", ...scaleSizingBlock()]
        }],
        /**
         * Width
         * @see https://tailwindcss.com/docs/width
         */
        w: [{
          w: [themeContainer, "screen", ...scaleSizing()]
        }],
        /**
         * Min-Width
         * @see https://tailwindcss.com/docs/min-width
         */
        "min-w": [{
          "min-w": [
            themeContainer,
            "screen",
            /** Deprecated. @see https://github.com/tailwindlabs/tailwindcss.com/issues/2027#issuecomment-2620152757 */
            "none",
            ...scaleSizing()
          ]
        }],
        /**
         * Max-Width
         * @see https://tailwindcss.com/docs/max-width
         */
        "max-w": [{
          "max-w": [
            themeContainer,
            "screen",
            "none",
            /** Deprecated since Tailwind CSS v4.0.0. @see https://github.com/tailwindlabs/tailwindcss.com/issues/2027#issuecomment-2620152757 */
            "prose",
            /** Deprecated since Tailwind CSS v4.0.0. @see https://github.com/tailwindlabs/tailwindcss.com/issues/2027#issuecomment-2620152757 */
            {
              screen: [themeBreakpoint]
            },
            ...scaleSizing()
          ]
        }],
        /**
         * Height
         * @see https://tailwindcss.com/docs/height
         */
        h: [{
          h: ["screen", "lh", ...scaleSizing()]
        }],
        /**
         * Min-Height
         * @see https://tailwindcss.com/docs/min-height
         */
        "min-h": [{
          "min-h": ["screen", "lh", "none", ...scaleSizing()]
        }],
        /**
         * Max-Height
         * @see https://tailwindcss.com/docs/max-height
         */
        "max-h": [{
          "max-h": ["screen", "lh", ...scaleSizing()]
        }],
        // ------------------
        // --- Typography ---
        // ------------------
        /**
         * Font Size
         * @see https://tailwindcss.com/docs/font-size
         */
        "font-size": [{
          text: ["base", themeText, isArbitraryVariableLength, isArbitraryLength]
        }],
        /**
         * Font Smoothing
         * @see https://tailwindcss.com/docs/font-smoothing
         */
        "font-smoothing": ["antialiased", "subpixel-antialiased"],
        /**
         * Font Style
         * @see https://tailwindcss.com/docs/font-style
         */
        "font-style": ["italic", "not-italic"],
        /**
         * Font Weight
         * @see https://tailwindcss.com/docs/font-weight
         */
        "font-weight": [{
          font: [themeFontWeight, isArbitraryVariableWeight, isArbitraryWeight]
        }],
        /**
         * Font Stretch
         * @see https://tailwindcss.com/docs/font-stretch
         */
        "font-stretch": [{
          "font-stretch": ["ultra-condensed", "extra-condensed", "condensed", "semi-condensed", "normal", "semi-expanded", "expanded", "extra-expanded", "ultra-expanded", isPercent, isArbitraryValue]
        }],
        /**
         * Font Family
         * @see https://tailwindcss.com/docs/font-family
         */
        "font-family": [{
          font: [isArbitraryVariableFamilyName, isArbitraryFamilyName, themeFont]
        }],
        /**
         * Font Feature Settings
         * @see https://tailwindcss.com/docs/font-feature-settings
         */
        "font-features": [{
          "font-features": [isArbitraryValue]
        }],
        /**
         * Font Variant Numeric
         * @see https://tailwindcss.com/docs/font-variant-numeric
         */
        "fvn-normal": ["normal-nums"],
        /**
         * Font Variant Numeric
         * @see https://tailwindcss.com/docs/font-variant-numeric
         */
        "fvn-ordinal": ["ordinal"],
        /**
         * Font Variant Numeric
         * @see https://tailwindcss.com/docs/font-variant-numeric
         */
        "fvn-slashed-zero": ["slashed-zero"],
        /**
         * Font Variant Numeric
         * @see https://tailwindcss.com/docs/font-variant-numeric
         */
        "fvn-figure": ["lining-nums", "oldstyle-nums"],
        /**
         * Font Variant Numeric
         * @see https://tailwindcss.com/docs/font-variant-numeric
         */
        "fvn-spacing": ["proportional-nums", "tabular-nums"],
        /**
         * Font Variant Numeric
         * @see https://tailwindcss.com/docs/font-variant-numeric
         */
        "fvn-fraction": ["diagonal-fractions", "stacked-fractions"],
        /**
         * Letter Spacing
         * @see https://tailwindcss.com/docs/letter-spacing
         */
        tracking: [{
          tracking: [themeTracking, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Line Clamp
         * @see https://tailwindcss.com/docs/line-clamp
         */
        "line-clamp": [{
          "line-clamp": [isNumber, "none", isArbitraryVariable, isArbitraryNumber]
        }],
        /**
         * Line Height
         * @see https://tailwindcss.com/docs/line-height
         */
        leading: [{
          leading: [
            /** Deprecated since Tailwind CSS v4.0.0. @see https://github.com/tailwindlabs/tailwindcss.com/issues/2027#issuecomment-2620152757 */
            themeLeading,
            ...scaleUnambiguousSpacing()
          ]
        }],
        /**
         * List Style Image
         * @see https://tailwindcss.com/docs/list-style-image
         */
        "list-image": [{
          "list-image": ["none", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * List Style Position
         * @see https://tailwindcss.com/docs/list-style-position
         */
        "list-style-position": [{
          list: ["inside", "outside"]
        }],
        /**
         * List Style Type
         * @see https://tailwindcss.com/docs/list-style-type
         */
        "list-style-type": [{
          list: ["disc", "decimal", "none", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Text Alignment
         * @see https://tailwindcss.com/docs/text-align
         */
        "text-alignment": [{
          text: ["left", "center", "right", "justify", "start", "end"]
        }],
        /**
         * Placeholder Color
         * @deprecated since Tailwind CSS v3.0.0
         * @see https://v3.tailwindcss.com/docs/placeholder-color
         */
        "placeholder-color": [{
          placeholder: scaleColor()
        }],
        /**
         * Text Color
         * @see https://tailwindcss.com/docs/text-color
         */
        "text-color": [{
          text: scaleColor()
        }],
        /**
         * Text Decoration
         * @see https://tailwindcss.com/docs/text-decoration
         */
        "text-decoration": ["underline", "overline", "line-through", "no-underline"],
        /**
         * Text Decoration Style
         * @see https://tailwindcss.com/docs/text-decoration-style
         */
        "text-decoration-style": [{
          decoration: [...scaleLineStyle(), "wavy"]
        }],
        /**
         * Text Decoration Thickness
         * @see https://tailwindcss.com/docs/text-decoration-thickness
         */
        "text-decoration-thickness": [{
          decoration: [isNumber, "from-font", "auto", isArbitraryVariable, isArbitraryLength]
        }],
        /**
         * Text Decoration Color
         * @see https://tailwindcss.com/docs/text-decoration-color
         */
        "text-decoration-color": [{
          decoration: scaleColor()
        }],
        /**
         * Text Underline Offset
         * @see https://tailwindcss.com/docs/text-underline-offset
         */
        "underline-offset": [{
          "underline-offset": [isNumber, "auto", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Text Transform
         * @see https://tailwindcss.com/docs/text-transform
         */
        "text-transform": ["uppercase", "lowercase", "capitalize", "normal-case"],
        /**
         * Text Overflow
         * @see https://tailwindcss.com/docs/text-overflow
         */
        "text-overflow": ["truncate", "text-ellipsis", "text-clip"],
        /**
         * Text Wrap
         * @see https://tailwindcss.com/docs/text-wrap
         */
        "text-wrap": [{
          text: ["wrap", "nowrap", "balance", "pretty"]
        }],
        /**
         * Text Indent
         * @see https://tailwindcss.com/docs/text-indent
         */
        indent: [{
          indent: scaleUnambiguousSpacing()
        }],
        /**
         * Tab Size
         * @see https://tailwindcss.com/docs/tab-size
         */
        "tab-size": [{
          tab: [isInteger, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Vertical Alignment
         * @see https://tailwindcss.com/docs/vertical-align
         */
        "vertical-align": [{
          align: ["baseline", "top", "middle", "bottom", "text-top", "text-bottom", "sub", "super", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Whitespace
         * @see https://tailwindcss.com/docs/whitespace
         */
        whitespace: [{
          whitespace: ["normal", "nowrap", "pre", "pre-line", "pre-wrap", "break-spaces"]
        }],
        /**
         * Word Break
         * @see https://tailwindcss.com/docs/word-break
         */
        break: [{
          break: ["normal", "words", "all", "keep"]
        }],
        /**
         * Overflow Wrap
         * @see https://tailwindcss.com/docs/overflow-wrap
         */
        wrap: [{
          wrap: ["break-word", "anywhere", "normal"]
        }],
        /**
         * Hyphens
         * @see https://tailwindcss.com/docs/hyphens
         */
        hyphens: [{
          hyphens: ["none", "manual", "auto"]
        }],
        /**
         * Content
         * @see https://tailwindcss.com/docs/content
         */
        content: [{
          content: ["none", isArbitraryVariable, isArbitraryValue]
        }],
        // -------------------
        // --- Backgrounds ---
        // -------------------
        /**
         * Background Attachment
         * @see https://tailwindcss.com/docs/background-attachment
         */
        "bg-attachment": [{
          bg: ["fixed", "local", "scroll"]
        }],
        /**
         * Background Clip
         * @see https://tailwindcss.com/docs/background-clip
         */
        "bg-clip": [{
          "bg-clip": ["border", "padding", "content", "text"]
        }],
        /**
         * Background Origin
         * @see https://tailwindcss.com/docs/background-origin
         */
        "bg-origin": [{
          "bg-origin": ["border", "padding", "content"]
        }],
        /**
         * Background Position
         * @see https://tailwindcss.com/docs/background-position
         */
        "bg-position": [{
          bg: scaleBgPosition()
        }],
        /**
         * Background Repeat
         * @see https://tailwindcss.com/docs/background-repeat
         */
        "bg-repeat": [{
          bg: scaleBgRepeat()
        }],
        /**
         * Background Size
         * @see https://tailwindcss.com/docs/background-size
         */
        "bg-size": [{
          bg: scaleBgSize()
        }],
        /**
         * Background Image
         * @see https://tailwindcss.com/docs/background-image
         */
        "bg-image": [{
          bg: ["none", {
            linear: [{
              to: ["t", "tr", "r", "br", "b", "bl", "l", "tl"]
            }, isInteger, isArbitraryVariable, isArbitraryValue],
            radial: ["", isArbitraryVariable, isArbitraryValue],
            conic: [isInteger, isArbitraryVariable, isArbitraryValue]
          }, isArbitraryVariableImage, isArbitraryImage]
        }],
        /**
         * Background Color
         * @see https://tailwindcss.com/docs/background-color
         */
        "bg-color": [{
          bg: scaleColor()
        }],
        /**
         * Gradient Color Stops From Position
         * @see https://tailwindcss.com/docs/gradient-color-stops
         */
        "gradient-from-pos": [{
          from: scaleGradientStopPosition()
        }],
        /**
         * Gradient Color Stops Via Position
         * @see https://tailwindcss.com/docs/gradient-color-stops
         */
        "gradient-via-pos": [{
          via: scaleGradientStopPosition()
        }],
        /**
         * Gradient Color Stops To Position
         * @see https://tailwindcss.com/docs/gradient-color-stops
         */
        "gradient-to-pos": [{
          to: scaleGradientStopPosition()
        }],
        /**
         * Gradient Color Stops From
         * @see https://tailwindcss.com/docs/gradient-color-stops
         */
        "gradient-from": [{
          from: scaleColor()
        }],
        /**
         * Gradient Color Stops Via
         * @see https://tailwindcss.com/docs/gradient-color-stops
         */
        "gradient-via": [{
          via: scaleColor()
        }],
        /**
         * Gradient Color Stops To
         * @see https://tailwindcss.com/docs/gradient-color-stops
         */
        "gradient-to": [{
          to: scaleColor()
        }],
        // ---------------
        // --- Borders ---
        // ---------------
        /**
         * Border Radius
         * @see https://tailwindcss.com/docs/border-radius
         */
        rounded: [{
          rounded: scaleRadius()
        }],
        /**
         * Border Radius Start
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-s": [{
          "rounded-s": scaleRadius()
        }],
        /**
         * Border Radius End
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-e": [{
          "rounded-e": scaleRadius()
        }],
        /**
         * Border Radius Top
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-t": [{
          "rounded-t": scaleRadius()
        }],
        /**
         * Border Radius Right
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-r": [{
          "rounded-r": scaleRadius()
        }],
        /**
         * Border Radius Bottom
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-b": [{
          "rounded-b": scaleRadius()
        }],
        /**
         * Border Radius Left
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-l": [{
          "rounded-l": scaleRadius()
        }],
        /**
         * Border Radius Start Start
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-ss": [{
          "rounded-ss": scaleRadius()
        }],
        /**
         * Border Radius Start End
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-se": [{
          "rounded-se": scaleRadius()
        }],
        /**
         * Border Radius End End
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-ee": [{
          "rounded-ee": scaleRadius()
        }],
        /**
         * Border Radius End Start
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-es": [{
          "rounded-es": scaleRadius()
        }],
        /**
         * Border Radius Top Left
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-tl": [{
          "rounded-tl": scaleRadius()
        }],
        /**
         * Border Radius Top Right
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-tr": [{
          "rounded-tr": scaleRadius()
        }],
        /**
         * Border Radius Bottom Right
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-br": [{
          "rounded-br": scaleRadius()
        }],
        /**
         * Border Radius Bottom Left
         * @see https://tailwindcss.com/docs/border-radius
         */
        "rounded-bl": [{
          "rounded-bl": scaleRadius()
        }],
        /**
         * Border Width
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w": [{
          border: scaleBorderWidth()
        }],
        /**
         * Border Width Inline
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-x": [{
          "border-x": scaleBorderWidth()
        }],
        /**
         * Border Width Block
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-y": [{
          "border-y": scaleBorderWidth()
        }],
        /**
         * Border Width Inline Start
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-s": [{
          "border-s": scaleBorderWidth()
        }],
        /**
         * Border Width Inline End
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-e": [{
          "border-e": scaleBorderWidth()
        }],
        /**
         * Border Width Block Start
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-bs": [{
          "border-bs": scaleBorderWidth()
        }],
        /**
         * Border Width Block End
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-be": [{
          "border-be": scaleBorderWidth()
        }],
        /**
         * Border Width Top
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-t": [{
          "border-t": scaleBorderWidth()
        }],
        /**
         * Border Width Right
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-r": [{
          "border-r": scaleBorderWidth()
        }],
        /**
         * Border Width Bottom
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-b": [{
          "border-b": scaleBorderWidth()
        }],
        /**
         * Border Width Left
         * @see https://tailwindcss.com/docs/border-width
         */
        "border-w-l": [{
          "border-l": scaleBorderWidth()
        }],
        /**
         * Divide Width X
         * @see https://tailwindcss.com/docs/border-width#between-children
         */
        "divide-x": [{
          "divide-x": scaleBorderWidth()
        }],
        /**
         * Divide Width X Reverse
         * @see https://tailwindcss.com/docs/border-width#between-children
         */
        "divide-x-reverse": ["divide-x-reverse"],
        /**
         * Divide Width Y
         * @see https://tailwindcss.com/docs/border-width#between-children
         */
        "divide-y": [{
          "divide-y": scaleBorderWidth()
        }],
        /**
         * Divide Width Y Reverse
         * @see https://tailwindcss.com/docs/border-width#between-children
         */
        "divide-y-reverse": ["divide-y-reverse"],
        /**
         * Border Style
         * @see https://tailwindcss.com/docs/border-style
         */
        "border-style": [{
          border: [...scaleLineStyle(), "hidden", "none"]
        }],
        /**
         * Divide Style
         * @see https://tailwindcss.com/docs/border-style#setting-the-divider-style
         */
        "divide-style": [{
          divide: [...scaleLineStyle(), "hidden", "none"]
        }],
        /**
         * Border Color
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color": [{
          border: scaleColor()
        }],
        /**
         * Border Color Inline
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-x": [{
          "border-x": scaleColor()
        }],
        /**
         * Border Color Block
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-y": [{
          "border-y": scaleColor()
        }],
        /**
         * Border Color Inline Start
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-s": [{
          "border-s": scaleColor()
        }],
        /**
         * Border Color Inline End
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-e": [{
          "border-e": scaleColor()
        }],
        /**
         * Border Color Block Start
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-bs": [{
          "border-bs": scaleColor()
        }],
        /**
         * Border Color Block End
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-be": [{
          "border-be": scaleColor()
        }],
        /**
         * Border Color Top
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-t": [{
          "border-t": scaleColor()
        }],
        /**
         * Border Color Right
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-r": [{
          "border-r": scaleColor()
        }],
        /**
         * Border Color Bottom
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-b": [{
          "border-b": scaleColor()
        }],
        /**
         * Border Color Left
         * @see https://tailwindcss.com/docs/border-color
         */
        "border-color-l": [{
          "border-l": scaleColor()
        }],
        /**
         * Divide Color
         * @see https://tailwindcss.com/docs/divide-color
         */
        "divide-color": [{
          divide: scaleColor()
        }],
        /**
         * Outline Style
         * @see https://tailwindcss.com/docs/outline-style
         */
        "outline-style": [{
          outline: [...scaleLineStyle(), "none", "hidden"]
        }],
        /**
         * Outline Offset
         * @see https://tailwindcss.com/docs/outline-offset
         */
        "outline-offset": [{
          "outline-offset": [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Outline Width
         * @see https://tailwindcss.com/docs/outline-width
         */
        "outline-w": [{
          outline: ["", isNumber, isArbitraryVariableLength, isArbitraryLength]
        }],
        /**
         * Outline Color
         * @see https://tailwindcss.com/docs/outline-color
         */
        "outline-color": [{
          outline: scaleColor()
        }],
        // ---------------
        // --- Effects ---
        // ---------------
        /**
         * Box Shadow
         * @see https://tailwindcss.com/docs/box-shadow
         */
        shadow: [{
          shadow: [
            // Deprecated since Tailwind CSS v4.0.0
            "",
            "none",
            themeShadow,
            isArbitraryVariableShadow,
            isArbitraryShadow
          ]
        }],
        /**
         * Box Shadow Color
         * @see https://tailwindcss.com/docs/box-shadow#setting-the-shadow-color
         */
        "shadow-color": [{
          shadow: scaleColor()
        }],
        /**
         * Inset Box Shadow
         * @see https://tailwindcss.com/docs/box-shadow#adding-an-inset-shadow
         */
        "inset-shadow": [{
          "inset-shadow": ["none", themeInsetShadow, isArbitraryVariableShadow, isArbitraryShadow]
        }],
        /**
         * Inset Box Shadow Color
         * @see https://tailwindcss.com/docs/box-shadow#setting-the-inset-shadow-color
         */
        "inset-shadow-color": [{
          "inset-shadow": scaleColor()
        }],
        /**
         * Ring Width
         * @see https://tailwindcss.com/docs/box-shadow#adding-a-ring
         */
        "ring-w": [{
          ring: scaleBorderWidth()
        }],
        /**
         * Ring Width Inset
         * @see https://v3.tailwindcss.com/docs/ring-width#inset-rings
         * @deprecated since Tailwind CSS v4.0.0
         * @see https://github.com/tailwindlabs/tailwindcss/blob/v4.0.0/packages/tailwindcss/src/utilities.ts#L4158
         */
        "ring-w-inset": ["ring-inset"],
        /**
         * Ring Color
         * @see https://tailwindcss.com/docs/box-shadow#setting-the-ring-color
         */
        "ring-color": [{
          ring: scaleColor()
        }],
        /**
         * Ring Offset Width
         * @see https://v3.tailwindcss.com/docs/ring-offset-width
         * @deprecated since Tailwind CSS v4.0.0
         * @see https://github.com/tailwindlabs/tailwindcss/blob/v4.0.0/packages/tailwindcss/src/utilities.ts#L4158
         */
        "ring-offset-w": [{
          "ring-offset": [isNumber, isArbitraryLength]
        }],
        /**
         * Ring Offset Color
         * @see https://v3.tailwindcss.com/docs/ring-offset-color
         * @deprecated since Tailwind CSS v4.0.0
         * @see https://github.com/tailwindlabs/tailwindcss/blob/v4.0.0/packages/tailwindcss/src/utilities.ts#L4158
         */
        "ring-offset-color": [{
          "ring-offset": scaleColor()
        }],
        /**
         * Inset Ring Width
         * @see https://tailwindcss.com/docs/box-shadow#adding-an-inset-ring
         */
        "inset-ring-w": [{
          "inset-ring": scaleBorderWidth()
        }],
        /**
         * Inset Ring Color
         * @see https://tailwindcss.com/docs/box-shadow#setting-the-inset-ring-color
         */
        "inset-ring-color": [{
          "inset-ring": scaleColor()
        }],
        /**
         * Text Shadow
         * @see https://tailwindcss.com/docs/text-shadow
         */
        "text-shadow": [{
          "text-shadow": ["none", themeTextShadow, isArbitraryVariableShadow, isArbitraryShadow]
        }],
        /**
         * Text Shadow Color
         * @see https://tailwindcss.com/docs/text-shadow#setting-the-shadow-color
         */
        "text-shadow-color": [{
          "text-shadow": scaleColor()
        }],
        /**
         * Opacity
         * @see https://tailwindcss.com/docs/opacity
         */
        opacity: [{
          opacity: [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Mix Blend Mode
         * @see https://tailwindcss.com/docs/mix-blend-mode
         */
        "mix-blend": [{
          "mix-blend": [...scaleBlendMode(), "plus-darker", "plus-lighter"]
        }],
        /**
         * Background Blend Mode
         * @see https://tailwindcss.com/docs/background-blend-mode
         */
        "bg-blend": [{
          "bg-blend": scaleBlendMode()
        }],
        /**
         * Mask Clip
         * @see https://tailwindcss.com/docs/mask-clip
         */
        "mask-clip": [{
          "mask-clip": ["border", "padding", "content", "fill", "stroke", "view"]
        }, "mask-no-clip"],
        /**
         * Mask Composite
         * @see https://tailwindcss.com/docs/mask-composite
         */
        "mask-composite": [{
          mask: ["add", "subtract", "intersect", "exclude"]
        }],
        /**
         * Mask Image
         * @see https://tailwindcss.com/docs/mask-image
         */
        "mask-image-linear-pos": [{
          "mask-linear": [isNumber]
        }],
        "mask-image-linear-from-pos": [{
          "mask-linear-from": scaleMaskImagePosition()
        }],
        "mask-image-linear-to-pos": [{
          "mask-linear-to": scaleMaskImagePosition()
        }],
        "mask-image-linear-from-color": [{
          "mask-linear-from": scaleColor()
        }],
        "mask-image-linear-to-color": [{
          "mask-linear-to": scaleColor()
        }],
        "mask-image-t-from-pos": [{
          "mask-t-from": scaleMaskImagePosition()
        }],
        "mask-image-t-to-pos": [{
          "mask-t-to": scaleMaskImagePosition()
        }],
        "mask-image-t-from-color": [{
          "mask-t-from": scaleColor()
        }],
        "mask-image-t-to-color": [{
          "mask-t-to": scaleColor()
        }],
        "mask-image-r-from-pos": [{
          "mask-r-from": scaleMaskImagePosition()
        }],
        "mask-image-r-to-pos": [{
          "mask-r-to": scaleMaskImagePosition()
        }],
        "mask-image-r-from-color": [{
          "mask-r-from": scaleColor()
        }],
        "mask-image-r-to-color": [{
          "mask-r-to": scaleColor()
        }],
        "mask-image-b-from-pos": [{
          "mask-b-from": scaleMaskImagePosition()
        }],
        "mask-image-b-to-pos": [{
          "mask-b-to": scaleMaskImagePosition()
        }],
        "mask-image-b-from-color": [{
          "mask-b-from": scaleColor()
        }],
        "mask-image-b-to-color": [{
          "mask-b-to": scaleColor()
        }],
        "mask-image-l-from-pos": [{
          "mask-l-from": scaleMaskImagePosition()
        }],
        "mask-image-l-to-pos": [{
          "mask-l-to": scaleMaskImagePosition()
        }],
        "mask-image-l-from-color": [{
          "mask-l-from": scaleColor()
        }],
        "mask-image-l-to-color": [{
          "mask-l-to": scaleColor()
        }],
        "mask-image-x-from-pos": [{
          "mask-x-from": scaleMaskImagePosition()
        }],
        "mask-image-x-to-pos": [{
          "mask-x-to": scaleMaskImagePosition()
        }],
        "mask-image-x-from-color": [{
          "mask-x-from": scaleColor()
        }],
        "mask-image-x-to-color": [{
          "mask-x-to": scaleColor()
        }],
        "mask-image-y-from-pos": [{
          "mask-y-from": scaleMaskImagePosition()
        }],
        "mask-image-y-to-pos": [{
          "mask-y-to": scaleMaskImagePosition()
        }],
        "mask-image-y-from-color": [{
          "mask-y-from": scaleColor()
        }],
        "mask-image-y-to-color": [{
          "mask-y-to": scaleColor()
        }],
        "mask-image-radial": [{
          "mask-radial": [isArbitraryVariable, isArbitraryValue]
        }],
        "mask-image-radial-from-pos": [{
          "mask-radial-from": scaleMaskImagePosition()
        }],
        "mask-image-radial-to-pos": [{
          "mask-radial-to": scaleMaskImagePosition()
        }],
        "mask-image-radial-from-color": [{
          "mask-radial-from": scaleColor()
        }],
        "mask-image-radial-to-color": [{
          "mask-radial-to": scaleColor()
        }],
        "mask-image-radial-shape": [{
          "mask-radial": ["circle", "ellipse"]
        }],
        "mask-image-radial-size": [{
          "mask-radial": [{
            closest: ["side", "corner"],
            farthest: ["side", "corner"]
          }]
        }],
        "mask-image-radial-pos": [{
          "mask-radial-at": scalePosition()
        }],
        "mask-image-conic-pos": [{
          "mask-conic": [isNumber]
        }],
        "mask-image-conic-from-pos": [{
          "mask-conic-from": scaleMaskImagePosition()
        }],
        "mask-image-conic-to-pos": [{
          "mask-conic-to": scaleMaskImagePosition()
        }],
        "mask-image-conic-from-color": [{
          "mask-conic-from": scaleColor()
        }],
        "mask-image-conic-to-color": [{
          "mask-conic-to": scaleColor()
        }],
        /**
         * Mask Mode
         * @see https://tailwindcss.com/docs/mask-mode
         */
        "mask-mode": [{
          mask: ["alpha", "luminance", "match"]
        }],
        /**
         * Mask Origin
         * @see https://tailwindcss.com/docs/mask-origin
         */
        "mask-origin": [{
          "mask-origin": ["border", "padding", "content", "fill", "stroke", "view"]
        }],
        /**
         * Mask Position
         * @see https://tailwindcss.com/docs/mask-position
         */
        "mask-position": [{
          mask: scaleBgPosition()
        }],
        /**
         * Mask Repeat
         * @see https://tailwindcss.com/docs/mask-repeat
         */
        "mask-repeat": [{
          mask: scaleBgRepeat()
        }],
        /**
         * Mask Size
         * @see https://tailwindcss.com/docs/mask-size
         */
        "mask-size": [{
          mask: scaleBgSize()
        }],
        /**
         * Mask Type
         * @see https://tailwindcss.com/docs/mask-type
         */
        "mask-type": [{
          "mask-type": ["alpha", "luminance"]
        }],
        /**
         * Mask Image
         * @see https://tailwindcss.com/docs/mask-image
         */
        "mask-image": [{
          mask: ["none", isArbitraryVariable, isArbitraryValue]
        }],
        // ---------------
        // --- Filters ---
        // ---------------
        /**
         * Filter
         * @see https://tailwindcss.com/docs/filter
         */
        filter: [{
          filter: [
            // Deprecated since Tailwind CSS v3.0.0
            "",
            "none",
            isArbitraryVariable,
            isArbitraryValue
          ]
        }],
        /**
         * Blur
         * @see https://tailwindcss.com/docs/blur
         */
        blur: [{
          blur: scaleBlur()
        }],
        /**
         * Brightness
         * @see https://tailwindcss.com/docs/brightness
         */
        brightness: [{
          brightness: [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Contrast
         * @see https://tailwindcss.com/docs/contrast
         */
        contrast: [{
          contrast: [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Drop Shadow
         * @see https://tailwindcss.com/docs/drop-shadow
         */
        "drop-shadow": [{
          "drop-shadow": [
            // Deprecated since Tailwind CSS v4.0.0
            "",
            "none",
            themeDropShadow,
            isArbitraryVariableShadow,
            isArbitraryShadow
          ]
        }],
        /**
         * Drop Shadow Color
         * @see https://tailwindcss.com/docs/filter-drop-shadow#setting-the-shadow-color
         */
        "drop-shadow-color": [{
          "drop-shadow": scaleColor()
        }],
        /**
         * Grayscale
         * @see https://tailwindcss.com/docs/grayscale
         */
        grayscale: [{
          grayscale: ["", isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Hue Rotate
         * @see https://tailwindcss.com/docs/hue-rotate
         */
        "hue-rotate": [{
          "hue-rotate": [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Invert
         * @see https://tailwindcss.com/docs/invert
         */
        invert: [{
          invert: ["", isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Saturate
         * @see https://tailwindcss.com/docs/saturate
         */
        saturate: [{
          saturate: [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Sepia
         * @see https://tailwindcss.com/docs/sepia
         */
        sepia: [{
          sepia: ["", isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Backdrop Filter
         * @see https://tailwindcss.com/docs/backdrop-filter
         */
        "backdrop-filter": [{
          "backdrop-filter": [
            // Deprecated since Tailwind CSS v3.0.0
            "",
            "none",
            isArbitraryVariable,
            isArbitraryValue
          ]
        }],
        /**
         * Backdrop Blur
         * @see https://tailwindcss.com/docs/backdrop-blur
         */
        "backdrop-blur": [{
          "backdrop-blur": scaleBlur()
        }],
        /**
         * Backdrop Brightness
         * @see https://tailwindcss.com/docs/backdrop-brightness
         */
        "backdrop-brightness": [{
          "backdrop-brightness": [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Backdrop Contrast
         * @see https://tailwindcss.com/docs/backdrop-contrast
         */
        "backdrop-contrast": [{
          "backdrop-contrast": [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Backdrop Grayscale
         * @see https://tailwindcss.com/docs/backdrop-grayscale
         */
        "backdrop-grayscale": [{
          "backdrop-grayscale": ["", isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Backdrop Hue Rotate
         * @see https://tailwindcss.com/docs/backdrop-hue-rotate
         */
        "backdrop-hue-rotate": [{
          "backdrop-hue-rotate": [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Backdrop Invert
         * @see https://tailwindcss.com/docs/backdrop-invert
         */
        "backdrop-invert": [{
          "backdrop-invert": ["", isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Backdrop Opacity
         * @see https://tailwindcss.com/docs/backdrop-opacity
         */
        "backdrop-opacity": [{
          "backdrop-opacity": [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Backdrop Saturate
         * @see https://tailwindcss.com/docs/backdrop-saturate
         */
        "backdrop-saturate": [{
          "backdrop-saturate": [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Backdrop Sepia
         * @see https://tailwindcss.com/docs/backdrop-sepia
         */
        "backdrop-sepia": [{
          "backdrop-sepia": ["", isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        // --------------
        // --- Tables ---
        // --------------
        /**
         * Border Collapse
         * @see https://tailwindcss.com/docs/border-collapse
         */
        "border-collapse": [{
          border: ["collapse", "separate"]
        }],
        /**
         * Border Spacing
         * @see https://tailwindcss.com/docs/border-spacing
         */
        "border-spacing": [{
          "border-spacing": scaleUnambiguousSpacing()
        }],
        /**
         * Border Spacing X
         * @see https://tailwindcss.com/docs/border-spacing
         */
        "border-spacing-x": [{
          "border-spacing-x": scaleUnambiguousSpacing()
        }],
        /**
         * Border Spacing Y
         * @see https://tailwindcss.com/docs/border-spacing
         */
        "border-spacing-y": [{
          "border-spacing-y": scaleUnambiguousSpacing()
        }],
        /**
         * Table Layout
         * @see https://tailwindcss.com/docs/table-layout
         */
        "table-layout": [{
          table: ["auto", "fixed"]
        }],
        /**
         * Caption Side
         * @see https://tailwindcss.com/docs/caption-side
         */
        caption: [{
          caption: ["top", "bottom"]
        }],
        // ---------------------------------
        // --- Transitions and Animation ---
        // ---------------------------------
        /**
         * Transition Property
         * @see https://tailwindcss.com/docs/transition-property
         */
        transition: [{
          transition: ["", "all", "colors", "opacity", "shadow", "transform", "none", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Transition Behavior
         * @see https://tailwindcss.com/docs/transition-behavior
         */
        "transition-behavior": [{
          transition: ["normal", "discrete"]
        }],
        /**
         * Transition Duration
         * @see https://tailwindcss.com/docs/transition-duration
         */
        duration: [{
          duration: [isNumber, "initial", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Transition Timing Function
         * @see https://tailwindcss.com/docs/transition-timing-function
         */
        ease: [{
          ease: ["linear", "initial", themeEase, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Transition Delay
         * @see https://tailwindcss.com/docs/transition-delay
         */
        delay: [{
          delay: [isNumber, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Animation
         * @see https://tailwindcss.com/docs/animation
         */
        animate: [{
          animate: ["none", themeAnimate, isArbitraryVariable, isArbitraryValue]
        }],
        // ------------------
        // --- Transforms ---
        // ------------------
        /**
         * Backface Visibility
         * @see https://tailwindcss.com/docs/backface-visibility
         */
        backface: [{
          backface: ["hidden", "visible"]
        }],
        /**
         * Perspective
         * @see https://tailwindcss.com/docs/perspective
         */
        perspective: [{
          perspective: [themePerspective, isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Perspective Origin
         * @see https://tailwindcss.com/docs/perspective-origin
         */
        "perspective-origin": [{
          "perspective-origin": scalePositionWithArbitrary()
        }],
        /**
         * Rotate
         * @see https://tailwindcss.com/docs/rotate
         */
        rotate: [{
          rotate: scaleRotate()
        }],
        /**
         * Rotate X
         * @see https://tailwindcss.com/docs/rotate
         */
        "rotate-x": [{
          "rotate-x": scaleRotate()
        }],
        /**
         * Rotate Y
         * @see https://tailwindcss.com/docs/rotate
         */
        "rotate-y": [{
          "rotate-y": scaleRotate()
        }],
        /**
         * Rotate Z
         * @see https://tailwindcss.com/docs/rotate
         */
        "rotate-z": [{
          "rotate-z": scaleRotate()
        }],
        /**
         * Scale
         * @see https://tailwindcss.com/docs/scale
         */
        scale: [{
          scale: scaleScale()
        }],
        /**
         * Scale X
         * @see https://tailwindcss.com/docs/scale
         */
        "scale-x": [{
          "scale-x": scaleScale()
        }],
        /**
         * Scale Y
         * @see https://tailwindcss.com/docs/scale
         */
        "scale-y": [{
          "scale-y": scaleScale()
        }],
        /**
         * Scale Z
         * @see https://tailwindcss.com/docs/scale
         */
        "scale-z": [{
          "scale-z": scaleScale()
        }],
        /**
         * Scale 3D
         * @see https://tailwindcss.com/docs/scale
         */
        "scale-3d": ["scale-3d"],
        /**
         * Skew
         * @see https://tailwindcss.com/docs/skew
         */
        skew: [{
          skew: scaleSkew()
        }],
        /**
         * Skew X
         * @see https://tailwindcss.com/docs/skew
         */
        "skew-x": [{
          "skew-x": scaleSkew()
        }],
        /**
         * Skew Y
         * @see https://tailwindcss.com/docs/skew
         */
        "skew-y": [{
          "skew-y": scaleSkew()
        }],
        /**
         * Transform
         * @see https://tailwindcss.com/docs/transform
         */
        transform: [{
          transform: [isArbitraryVariable, isArbitraryValue, "", "none", "gpu", "cpu"]
        }],
        /**
         * Transform Origin
         * @see https://tailwindcss.com/docs/transform-origin
         */
        "transform-origin": [{
          origin: scalePositionWithArbitrary()
        }],
        /**
         * Transform Style
         * @see https://tailwindcss.com/docs/transform-style
         */
        "transform-style": [{
          transform: ["3d", "flat"]
        }],
        /**
         * Translate
         * @see https://tailwindcss.com/docs/translate
         */
        translate: [{
          translate: scaleTranslate()
        }],
        /**
         * Translate X
         * @see https://tailwindcss.com/docs/translate
         */
        "translate-x": [{
          "translate-x": scaleTranslate()
        }],
        /**
         * Translate Y
         * @see https://tailwindcss.com/docs/translate
         */
        "translate-y": [{
          "translate-y": scaleTranslate()
        }],
        /**
         * Translate Z
         * @see https://tailwindcss.com/docs/translate
         */
        "translate-z": [{
          "translate-z": scaleTranslate()
        }],
        /**
         * Translate None
         * @see https://tailwindcss.com/docs/translate
         */
        "translate-none": ["translate-none"],
        /**
         * Zoom
         * @see https://tailwindcss.com/docs/zoom
         */
        zoom: [{
          zoom: [isInteger, isArbitraryVariable, isArbitraryValue]
        }],
        // ---------------------
        // --- Interactivity ---
        // ---------------------
        /**
         * Accent Color
         * @see https://tailwindcss.com/docs/accent-color
         */
        accent: [{
          accent: scaleColor()
        }],
        /**
         * Appearance
         * @see https://tailwindcss.com/docs/appearance
         */
        appearance: [{
          appearance: ["none", "auto"]
        }],
        /**
         * Caret Color
         * @see https://tailwindcss.com/docs/just-in-time-mode#caret-color-utilities
         */
        "caret-color": [{
          caret: scaleColor()
        }],
        /**
         * Color Scheme
         * @see https://tailwindcss.com/docs/color-scheme
         */
        "color-scheme": [{
          scheme: ["normal", "dark", "light", "light-dark", "only-dark", "only-light"]
        }],
        /**
         * Cursor
         * @see https://tailwindcss.com/docs/cursor
         */
        cursor: [{
          cursor: ["auto", "default", "pointer", "wait", "text", "move", "help", "not-allowed", "none", "context-menu", "progress", "cell", "crosshair", "vertical-text", "alias", "copy", "no-drop", "grab", "grabbing", "all-scroll", "col-resize", "row-resize", "n-resize", "e-resize", "s-resize", "w-resize", "ne-resize", "nw-resize", "se-resize", "sw-resize", "ew-resize", "ns-resize", "nesw-resize", "nwse-resize", "zoom-in", "zoom-out", isArbitraryVariable, isArbitraryValue]
        }],
        /**
         * Field Sizing
         * @see https://tailwindcss.com/docs/field-sizing
         */
        "field-sizing": [{
          "field-sizing": ["fixed", "content"]
        }],
        /**
         * Pointer Events
         * @see https://tailwindcss.com/docs/pointer-events
         */
        "pointer-events": [{
          "pointer-events": ["auto", "none"]
        }],
        /**
         * Resize
         * @see https://tailwindcss.com/docs/resize
         */
        resize: [{
          resize: ["none", "", "y", "x"]
        }],
        /**
         * Scroll Behavior
         * @see https://tailwindcss.com/docs/scroll-behavior
         */
        "scroll-behavior": [{
          scroll: ["auto", "smooth"]
        }],
        /**
         * Scrollbar Thumb Color
         * @see https://tailwindcss.com/docs/scrollbar-color
         */
        "scrollbar-thumb-color": [{
          "scrollbar-thumb": scaleColor()
        }],
        /**
         * Scrollbar Track Color
         * @see https://tailwindcss.com/docs/scrollbar-color
         */
        "scrollbar-track-color": [{
          "scrollbar-track": scaleColor()
        }],
        /**
         * Scrollbar Gutter
         * @see https://tailwindcss.com/docs/scrollbar-gutter
         */
        "scrollbar-gutter": [{
          "scrollbar-gutter": ["auto", "stable", "both"]
        }],
        /**
         * Scrollbar Width
         * @see https://tailwindcss.com/docs/scrollbar-width
         */
        "scrollbar-w": [{
          scrollbar: ["auto", "thin", "none"]
        }],
        /**
         * Scroll Margin
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-m": [{
          "scroll-m": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Inline
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-mx": [{
          "scroll-mx": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Block
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-my": [{
          "scroll-my": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Inline Start
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-ms": [{
          "scroll-ms": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Inline End
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-me": [{
          "scroll-me": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Block Start
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-mbs": [{
          "scroll-mbs": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Block End
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-mbe": [{
          "scroll-mbe": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Top
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-mt": [{
          "scroll-mt": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Right
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-mr": [{
          "scroll-mr": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Bottom
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-mb": [{
          "scroll-mb": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Margin Left
         * @see https://tailwindcss.com/docs/scroll-margin
         */
        "scroll-ml": [{
          "scroll-ml": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-p": [{
          "scroll-p": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Inline
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-px": [{
          "scroll-px": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Block
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-py": [{
          "scroll-py": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Inline Start
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-ps": [{
          "scroll-ps": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Inline End
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-pe": [{
          "scroll-pe": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Block Start
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-pbs": [{
          "scroll-pbs": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Block End
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-pbe": [{
          "scroll-pbe": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Top
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-pt": [{
          "scroll-pt": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Right
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-pr": [{
          "scroll-pr": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Bottom
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-pb": [{
          "scroll-pb": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Padding Left
         * @see https://tailwindcss.com/docs/scroll-padding
         */
        "scroll-pl": [{
          "scroll-pl": scaleUnambiguousSpacing()
        }],
        /**
         * Scroll Snap Align
         * @see https://tailwindcss.com/docs/scroll-snap-align
         */
        "snap-align": [{
          snap: ["start", "end", "center", "align-none"]
        }],
        /**
         * Scroll Snap Stop
         * @see https://tailwindcss.com/docs/scroll-snap-stop
         */
        "snap-stop": [{
          snap: ["normal", "always"]
        }],
        /**
         * Scroll Snap Type
         * @see https://tailwindcss.com/docs/scroll-snap-type
         */
        "snap-type": [{
          snap: ["none", "x", "y", "both"]
        }],
        /**
         * Scroll Snap Type Strictness
         * @see https://tailwindcss.com/docs/scroll-snap-type
         */
        "snap-strictness": [{
          snap: ["mandatory", "proximity"]
        }],
        /**
         * Touch Action
         * @see https://tailwindcss.com/docs/touch-action
         */
        touch: [{
          touch: ["auto", "none", "manipulation"]
        }],
        /**
         * Touch Action X
         * @see https://tailwindcss.com/docs/touch-action
         */
        "touch-x": [{
          "touch-pan": ["x", "left", "right"]
        }],
        /**
         * Touch Action Y
         * @see https://tailwindcss.com/docs/touch-action
         */
        "touch-y": [{
          "touch-pan": ["y", "up", "down"]
        }],
        /**
         * Touch Action Pinch Zoom
         * @see https://tailwindcss.com/docs/touch-action
         */
        "touch-pz": ["touch-pinch-zoom"],
        /**
         * User Select
         * @see https://tailwindcss.com/docs/user-select
         */
        select: [{
          select: ["none", "text", "all", "auto"]
        }],
        /**
         * Will Change
         * @see https://tailwindcss.com/docs/will-change
         */
        "will-change": [{
          "will-change": ["auto", "scroll", "contents", "transform", isArbitraryVariable, isArbitraryValue]
        }],
        // -----------
        // --- SVG ---
        // -----------
        /**
         * Fill
         * @see https://tailwindcss.com/docs/fill
         */
        fill: [{
          fill: ["none", ...scaleColor()]
        }],
        /**
         * Stroke Width
         * @see https://tailwindcss.com/docs/stroke-width
         */
        "stroke-w": [{
          stroke: [isNumber, isArbitraryVariableLength, isArbitraryLength, isArbitraryNumber]
        }],
        /**
         * Stroke
         * @see https://tailwindcss.com/docs/stroke
         */
        stroke: [{
          stroke: ["none", ...scaleColor()]
        }],
        // ---------------------
        // --- Accessibility ---
        // ---------------------
        /**
         * Forced Color Adjust
         * @see https://tailwindcss.com/docs/forced-color-adjust
         */
        "forced-color-adjust": [{
          "forced-color-adjust": ["auto", "none"]
        }]
      },
      conflictingClassGroups: {
        "container-named": ["container-type"],
        overflow: ["overflow-x", "overflow-y"],
        overscroll: ["overscroll-x", "overscroll-y"],
        inset: ["inset-x", "inset-y", "inset-bs", "inset-be", "start", "end", "top", "right", "bottom", "left"],
        "inset-x": ["right", "left"],
        "inset-y": ["top", "bottom"],
        flex: ["basis", "grow", "shrink"],
        gap: ["gap-x", "gap-y"],
        p: ["px", "py", "ps", "pe", "pbs", "pbe", "pt", "pr", "pb", "pl"],
        px: ["pr", "pl"],
        py: ["pt", "pb"],
        m: ["mx", "my", "ms", "me", "mbs", "mbe", "mt", "mr", "mb", "ml"],
        mx: ["mr", "ml"],
        my: ["mt", "mb"],
        size: ["w", "h"],
        "font-size": ["leading"],
        "fvn-normal": ["fvn-ordinal", "fvn-slashed-zero", "fvn-figure", "fvn-spacing", "fvn-fraction"],
        "fvn-ordinal": ["fvn-normal"],
        "fvn-slashed-zero": ["fvn-normal"],
        "fvn-figure": ["fvn-normal"],
        "fvn-spacing": ["fvn-normal"],
        "fvn-fraction": ["fvn-normal"],
        "line-clamp": ["display", "overflow"],
        rounded: ["rounded-s", "rounded-e", "rounded-t", "rounded-r", "rounded-b", "rounded-l", "rounded-ss", "rounded-se", "rounded-ee", "rounded-es", "rounded-tl", "rounded-tr", "rounded-br", "rounded-bl"],
        "rounded-s": ["rounded-ss", "rounded-es"],
        "rounded-e": ["rounded-se", "rounded-ee"],
        "rounded-t": ["rounded-tl", "rounded-tr"],
        "rounded-r": ["rounded-tr", "rounded-br"],
        "rounded-b": ["rounded-br", "rounded-bl"],
        "rounded-l": ["rounded-tl", "rounded-bl"],
        "border-spacing": ["border-spacing-x", "border-spacing-y"],
        "border-w": ["border-w-x", "border-w-y", "border-w-s", "border-w-e", "border-w-bs", "border-w-be", "border-w-t", "border-w-r", "border-w-b", "border-w-l"],
        "border-w-x": ["border-w-r", "border-w-l"],
        "border-w-y": ["border-w-t", "border-w-b"],
        "border-color": ["border-color-x", "border-color-y", "border-color-s", "border-color-e", "border-color-bs", "border-color-be", "border-color-t", "border-color-r", "border-color-b", "border-color-l"],
        "border-color-x": ["border-color-r", "border-color-l"],
        "border-color-y": ["border-color-t", "border-color-b"],
        translate: ["translate-x", "translate-y", "translate-none"],
        "translate-none": ["translate", "translate-x", "translate-y", "translate-z"],
        "scroll-m": ["scroll-mx", "scroll-my", "scroll-ms", "scroll-me", "scroll-mbs", "scroll-mbe", "scroll-mt", "scroll-mr", "scroll-mb", "scroll-ml"],
        "scroll-mx": ["scroll-mr", "scroll-ml"],
        "scroll-my": ["scroll-mt", "scroll-mb"],
        "scroll-p": ["scroll-px", "scroll-py", "scroll-ps", "scroll-pe", "scroll-pbs", "scroll-pbe", "scroll-pt", "scroll-pr", "scroll-pb", "scroll-pl"],
        "scroll-px": ["scroll-pr", "scroll-pl"],
        "scroll-py": ["scroll-pt", "scroll-pb"],
        touch: ["touch-x", "touch-y", "touch-pz"],
        "touch-x": ["touch"],
        "touch-y": ["touch"],
        "touch-pz": ["touch"]
      },
      conflictingClassGroupModifiers: {
        "font-size": ["leading"]
      },
      postfixLookupClassGroups: ["container-type"],
      orderSensitiveModifiers: ["*", "**", "after", "backdrop", "before", "details-content", "file", "first-letter", "first-line", "marker", "placeholder", "selection"]
    };
  };
  const twMerge = /* @__PURE__ */ createTailwindMerge(getDefaultConfig);
  function cn(...values) {
    return twMerge(clsx(values));
  }
  function Button({
    className,
    variant = "subtle",
    size = "md",
    children,
    ...props
  }) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      "button",
      {
        type: "button",
        className: cn(
          "inline-flex items-center justify-center gap-2 rounded-lg border border-solid transition-colors disabled:cursor-not-allowed disabled:opacity-45",
          size === "sm" && "h-8 px-2.5 text-xs",
          size === "md" && "h-9 px-3 text-sm",
          size === "icon" && "size-9 p-0",
          variant === "primary" && "border-primary bg-primary text-primaryAccent hover:bg-primary/85",
          variant === "subtle" && "border-border bg-accent text-primary hover:bg-background-secondary",
          variant === "ghost" && "border-transparent bg-transparent text-muted hover:bg-accent hover:text-primary",
          variant === "danger" && "border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/20",
          className
        ),
        ...props,
        children
      }
    );
  }
  function PickerSearch({
    trailing,
    containerClassName,
    className,
    ...inputProps
  }) {
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: cn(
      "sticky top-0 z-10 flex min-h-12 items-center gap-2 border-b border-border/60 bg-white px-2 py-2",
      containerClassName
    ), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-background-secondary shadow-[inset_0_1px_2px_rgba(15,23,42,0.04)] px-2.5 transition-colors focus-within:border-primary/35 focus-within:bg-white focus-within:outline focus-within:outline-1 focus-within:outline-primary/15 focus-within:shadow-[0_0_0_3px_rgba(59,130,246,0.07)]", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(Search, { size: 14, className: "shrink-0 text-muted" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "input",
          {
            ...inputProps,
            className: cn(
              "min-w-0 flex-1 border-0 bg-transparent text-xs text-primary outline-none placeholder:text-muted",
              className
            )
          }
        )
      ] }),
      trailing ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0 text-[10px] text-muted", children: trailing }) : null
    ] });
  }
  const MAX_MENTIONS = 5;
  const PAGE_ACTIONS = /* @__PURE__ */ new Set(["open", "create", "view", "edit", "apply"]);
  const ACTION_LABELS = {
    read: "引用数据",
    open: "打开",
    create: "新建",
    view: "打开查看",
    edit: "打开编辑",
    apply: "应用"
  };
  const CATEGORIES = [
    { scope: "menu", label: "菜单", detail: "按完整路径打开菜单，或直接进入新建" },
    { scope: "record", label: "业务记录", detail: "查找客户、订单、合同等具体业务记录" },
    { scope: "skill", label: "技能", detail: "选择适合当前任务的专业能力" }
  ];
  function MentionIcon({ kind }) {
    return kind === "menu" ? /* @__PURE__ */ jsxRuntimeExports.jsx(Menu, { size: 15 }) : /* @__PURE__ */ jsxRuntimeExports.jsx(Database, { size: 15 });
  }
  function CategoryIcon({ scope }) {
    return scope === "skill" ? /* @__PURE__ */ jsxRuntimeExports.jsx(Sparkles, { size: 15 }) : /* @__PURE__ */ jsxRuntimeExports.jsx(MentionIcon, { kind: scope });
  }
  function ActionIcon({ action }) {
    if (action === "create") return /* @__PURE__ */ jsxRuntimeExports.jsx(Plus, { size: 14 });
    if (action === "view") return /* @__PURE__ */ jsxRuntimeExports.jsx(Eye, { size: 14 });
    if (action === "edit") return /* @__PURE__ */ jsxRuntimeExports.jsx(Pencil, { size: 14 });
    return /* @__PURE__ */ jsxRuntimeExports.jsx(AtSign, { size: 14 });
  }
  function conflictReason(candidate, action, selected, workspaceReferenceCount = 0) {
    if (selected.length + workspaceReferenceCount >= MAX_MENTIONS) return "已达到 5 个引用上限";
    if (selected.some((item) => item.resourceKey === candidate.resourceKey)) return "已引用此对象";
    if (action && PAGE_ACTIONS.has(action) && selected.some((item) => item.pageAction)) {
      return "本条消息已有页面动作";
    }
    return "";
  }
  const MentionPicker = reactExports.forwardRef(function MentionPicker2({
    open,
    query,
    selected,
    workspaceReferenceCount,
    hostBridge,
    onSelect,
    onOpenSkills,
    onClose
  }, ref) {
    var _a, _b, _c;
    const [view, setView] = reactExports.useState("home");
    const [scope, setScope] = reactExports.useState("all");
    const [modelScope, setModelScope] = reactExports.useState("");
    const [modelQuery, setModelQuery] = reactExports.useState("");
    const [searchText, setSearchText] = reactExports.useState(query.query);
    const [models, setModels] = reactExports.useState([]);
    const [candidates, setCandidates] = reactExports.useState([]);
    const [pending, setPending] = reactExports.useState(null);
    const [activeIndex, setActiveIndex] = reactExports.useState(0);
    const [loading, setLoading] = reactExports.useState(false);
    const [binding, setBinding] = reactExports.useState(false);
    const [error, setError] = reactExports.useState("");
    const pickerRef = reactExports.useRef(null);
    const requestNumber = reactExports.useRef(0);
    const normalizedQuery = searchText.trim();
    reactExports.useEffect(() => setSearchText(query.query), [query.query]);
    reactExports.useEffect(() => {
      var _a2;
      if (open && (view === "home" || view === "actions")) {
        (_a2 = pickerRef.current) == null ? void 0 : _a2.focus({ preventScroll: true });
      }
    }, [open, view]);
    reactExports.useEffect(() => {
      if (!open) {
        requestNumber.current += 1;
        return;
      }
      setView(normalizedQuery ? "results" : "home");
      setScope("all");
      setModelScope("");
      setPending(null);
      setCandidates([]);
      setError("");
      setActiveIndex(0);
    }, [open]);
    reactExports.useEffect(() => {
      if (!open) return;
      if (normalizedQuery && view === "home") {
        setView("results");
        setScope("all");
      } else if (!normalizedQuery && view === "results" && scope === "all") {
        setView("home");
      }
      setActiveIndex(0);
    }, [normalizedQuery]);
    reactExports.useEffect(() => {
      const canBrowseEmpty = scope === "menu";
      const shouldSearch = open && (view === "models" || view === "results" && (normalizedQuery.length >= 2 || canBrowseEmpty));
      const currentRequest = ++requestNumber.current;
      setCandidates([]);
      setError("");
      setActiveIndex(0);
      if (!shouldSearch || !hostBridge.searchMentions) {
        setLoading(false);
        return;
      }
      setLoading(true);
      const timer = window.setTimeout(() => {
        const search2 = hostBridge.searchMentions({
          query: view === "models" ? "" : normalizedQuery,
          scope: view === "models" ? "record" : scope,
          modelScope: modelScope || void 0
        });
        Promise.resolve(search2).then((result) => {
          if (currentRequest !== requestNumber.current) return;
          if ((result == null ? void 0 : result.ok) === false) {
            setError(result.error || result.code || "对象搜索失败");
            return;
          }
          setCandidates(((result == null ? void 0 : result.candidates) || []).filter((item) => item.kind === "record" || item.kind === "menu"));
          setModels(((result == null ? void 0 : result.modelScopes) || []).slice(0, 100));
        }, (reason) => {
          if (currentRequest !== requestNumber.current) return;
          setError((reason == null ? void 0 : reason.message) || "对象搜索失败");
        }).finally(() => {
          if (currentRequest === requestNumber.current) setLoading(false);
        });
      }, view === "models" || !normalizedQuery ? 0 : 300);
      return () => window.clearTimeout(timer);
    }, [hostBridge, modelScope, normalizedQuery, open, scope, view]);
    const filteredModels = reactExports.useMemo(() => {
      const needle = modelQuery.trim().toLocaleLowerCase();
      return models.filter(
        (item) => !needle || item.label.toLocaleLowerCase().includes(needle) || item.model.includes(needle)
      );
    }, [modelQuery, models]);
    const bind = async (candidate, action) => {
      const reason = conflictReason(candidate, action, selected, workspaceReferenceCount);
      if (reason || binding || !hostBridge.bindMention) {
        if (reason) setError(reason);
        return;
      }
      setBinding(true);
      setError("");
      try {
        const result = await Promise.resolve(hostBridge.bindMention({
          candidateToken: candidate.candidateToken,
          action
        }));
        if (!(result == null ? void 0 : result.ok) || !result.reference) {
          setError((result == null ? void 0 : result.error) || (result == null ? void 0 : result.code) || "对象绑定失败");
          return;
        }
        onSelect(result.reference);
      } catch (reason2) {
        setError((reason2 == null ? void 0 : reason2.message) || "对象绑定失败");
      } finally {
        setBinding(false);
      }
    };
    const selectCandidate = (candidate) => {
      const allBlocked = candidate.actions.every((action) => conflictReason(candidate, action, selected, workspaceReferenceCount));
      if (allBlocked) return;
      const defaultAction = candidate.kind === "record" ? "read" : "open";
      if (candidate.actions.includes(defaultAction)) {
        void bind(candidate, defaultAction);
        return;
      }
      void bind(candidate, candidate.actions[0]);
    };
    const goBack = () => {
      setError("");
      setActiveIndex(0);
      if (view === "actions") {
        setPending(null);
        setView("results");
      } else if (view === "models" || scope !== "all") {
        setScope("all");
        setModelScope("");
        setView(normalizedQuery ? "results" : "home");
      } else {
        onClose();
      }
    };
    const optionCount = view === "actions" ? (pending == null ? void 0 : pending.actions.length) || 0 : view === "models" ? filteredModels.length : view === "results" ? candidates.length : CATEGORIES.length;
    const activate = (index2) => {
      if (view === "actions" && (pending == null ? void 0 : pending.actions[index2])) {
        void bind(pending, pending.actions[index2]);
      } else if (view === "models" && filteredModels[index2]) {
        setModelScope(filteredModels[index2].model);
        setScope("record");
        setView("results");
        setActiveIndex(0);
      } else if (view === "results" && candidates[index2]) {
        selectCandidate(candidates[index2]);
      } else if (view === "home") {
        const category = CATEGORIES[index2];
        if (!category) return;
        if (category.scope === "skill") {
          onOpenSkills();
          return;
        }
        setSearchText("");
        setScope(category.scope);
        setActiveIndex(0);
        setView(category.scope === "record" ? "models" : "results");
      }
    };
    const activeOptionId = view === "home" ? `agui-mention-category-${((_a = CATEGORIES[activeIndex]) == null ? void 0 : _a.scope) || "none"}` : view === "models" ? `agui-mention-model-${((_b = filteredModels[activeIndex]) == null ? void 0 : _b.model) || "none"}` : view === "results" ? `agui-mention-candidate-${((_c = candidates[activeIndex]) == null ? void 0 : _c.candidateToken) || "none"}` : `agui-mention-action-${(pending == null ? void 0 : pending.actions[activeIndex]) || "none"}`;
    const handleKey = (event) => {
      var _a2;
      if (!open || event.nativeEvent.isComposing) return false;
      if (event.key === "Escape") {
        event.preventDefault();
        goBack();
        return true;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goBack();
        return true;
      }
      if (event.key === "ArrowRight" && view === "results" && ((_a2 = candidates[activeIndex]) == null ? void 0 : _a2.actions.length) > 1) {
        event.preventDefault();
        setPending(candidates[activeIndex]);
        setView("actions");
        setActiveIndex(0);
        return true;
      }
      if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        setActiveIndex(event.key === "Home" ? 0 : Math.max(0, optionCount - 1));
        return true;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        setActiveIndex((value) => optionCount ? (value + delta + optionCount) % optionCount : 0);
        return true;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        activate(activeIndex);
        return true;
      }
      return false;
    };
    reactExports.useImperativeHandle(ref, () => ({
      handleKey: (event) => handleKey(event)
    }));
    if (!open) return null;
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "div",
      {
        ref: pickerRef,
        tabIndex: -1,
        className: "agui-picker absolute outline-none bottom-full left-0 z-40 mb-2 w-full max-w-md overflow-hidden rounded-md border border-border/70 bg-white text-secondary shadow-[0_12px_32px_rgba(15,23,42,0.14)]",
        role: "dialog",
        onKeyDown: (event) => handleKey(event),
        "aria-label": "添加到对话",
        children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex h-9 items-center gap-2 border-b border-border px-2", children: [
            view !== "home" ? /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center rounded-md border-0 bg-background-secondary text-secondary shadow-none transition-colors hover:bg-accent hover:text-primary", "aria-label": "返回", onPointerDown: (event) => event.preventDefault(), onClick: goBack, children: /* @__PURE__ */ jsxRuntimeExports.jsx(ArrowLeft, { size: 15 }) }) : /* @__PURE__ */ jsxRuntimeExports.jsx(AtSign, { size: 15, className: "mx-1 text-muted" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "min-w-0 flex-1 truncate text-xs font-medium", children: view === "home" ? "添加到对话" : view === "actions" ? pending == null ? void 0 : pending.label : view === "models" ? "选择业务类型" : scope === "menu" ? "选择菜单" : scope === "record" ? "搜索业务记录" : "搜索结果" })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { id: "agui-mention-options", className: "max-h-72 overflow-y-auto p-1", role: "listbox", "aria-busy": loading, "aria-activedescendant": activeOptionId, children: [
            view === "home" ? CATEGORIES.map((category, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { id: `agui-mention-category-${category.scope}`, type: "button", role: "option", "aria-selected": index2 === activeIndex, className: cn("flex h-12 w-full items-center gap-2 border-l-2 border-l-transparent bg-white px-2 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary", index2 === activeIndex && "border-l-primary bg-background-secondary text-primary"), onPointerDown: (event) => event.preventDefault(), onClick: () => activate(index2), children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "grid size-7 shrink-0 place-items-center text-muted", children: /* @__PURE__ */ jsxRuntimeExports.jsx(CategoryIcon, { scope: category.scope }) }),
              /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "min-w-0 flex-1", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block text-xs text-primary", children: category.label }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block truncate text-[10px] text-muted", children: category.detail })
              ] })
            ] }, category.scope)) : null,
            view === "models" ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(PickerSearch, { autoFocus: true, value: modelQuery, onChange: (event) => {
                setModelQuery(event.target.value);
                setActiveIndex(0);
              }, placeholder: "搜索业务类型", "aria-label": "搜索业务类型" }),
              filteredModels.map((model, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { id: `agui-mention-model-${model.model}`, type: "button", role: "option", "aria-selected": index2 === activeIndex, className: cn("group flex min-h-12 w-full items-center gap-2.5 border-l-2 border-l-transparent bg-white px-2.5 py-1.5 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary", index2 === activeIndex && "border-l-primary bg-background-secondary text-primary"), onClick: () => activate(index2), children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "grid size-7 shrink-0 place-items-center rounded-md bg-background-secondary text-muted transition-colors group-hover:bg-white group-hover:text-primary", children: /* @__PURE__ */ jsxRuntimeExports.jsx(FolderTree, { size: 15 }) }),
                /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "min-w-0 flex-1", children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block truncate text-xs font-medium text-primary", children: model.label }),
                  /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mt-0.5 block truncate text-[10px] text-muted", children: model.model })
                ] }),
                /* @__PURE__ */ jsxRuntimeExports.jsx(ArrowLeft, { size: 13, className: "shrink-0 rotate-180 text-muted/60 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" })
              ] }, model.model)),
              !filteredModels.length && !loading ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "grid min-h-28 place-items-center px-4 text-center text-xs text-muted", children: "没有匹配的业务类型" }) : null
            ] }) : null,
            view === "results" ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(PickerSearch, { autoFocus: true, value: searchText, onChange: (event) => {
                setSearchText(event.target.value);
                setActiveIndex(0);
              }, placeholder: scope === "menu" ? "搜索菜单名称或完整路径" : scope === "record" ? "搜索记录名称" : "搜索记录或菜单", "aria-label": scope === "menu" ? "搜索菜单" : scope === "record" ? "搜索业务记录" : "搜索记录或菜单" }),
              loading ? Array.from({ length: 4 }).map((_, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex h-11 animate-pulse items-center gap-2 px-2", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "size-6 bg-accent" }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "h-3 flex-1 bg-accent" })
              ] }, index2)) : null,
              !loading && candidates.map((candidate, index2) => {
                const reasons = candidate.actions.map((action) => conflictReason(candidate, action, selected, workspaceReferenceCount)).filter(Boolean);
                const disabled = reasons.length === candidate.actions.length;
                return /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { id: `agui-mention-candidate-${candidate.candidateToken}`, type: "button", role: "option", "aria-selected": index2 === activeIndex, disabled: disabled || binding, className: cn("group flex min-h-12 w-full items-center gap-2.5 border-l-2 border-l-transparent bg-white px-2.5 py-1.5 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary disabled:opacity-40", index2 === activeIndex && "border-l-primary bg-background-secondary text-primary"), onPointerDown: (event) => event.preventDefault(), onClick: () => selectCandidate(candidate), title: disabled ? reasons[0] : candidate.detail, children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "grid size-7 shrink-0 place-items-center rounded-md bg-background-secondary text-muted transition-colors group-hover:bg-white group-hover:text-primary", children: /* @__PURE__ */ jsxRuntimeExports.jsx(MentionIcon, { kind: candidate.kind }) }),
                  /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "min-w-0 flex-1", children: [
                    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block truncate text-xs font-medium text-primary", children: candidate.label }),
                    /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mt-0.5 block truncate text-[10px] text-muted", children: disabled ? reasons[0] : candidate.detail })
                  ] }),
                  candidate.kind === "menu" && candidate.actions.includes("create") ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "grid size-6 shrink-0 place-items-center rounded-md bg-background-secondary text-muted transition-colors group-hover:bg-white group-hover:text-primary", title: "支持新建", children: /* @__PURE__ */ jsxRuntimeExports.jsx(Plus, { size: 13 }) }) : candidate.actions.length > 1 ? /* @__PURE__ */ jsxRuntimeExports.jsx(ArrowLeft, { size: 13, className: "shrink-0 rotate-180 text-muted/60 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" }) : null
                ] }, candidate.candidateToken);
              }),
              !loading && !candidates.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "px-3 py-5 text-center text-xs text-muted", children: error || (scope === "record" && normalizedQuery.length < 2 ? "输入至少 2 个字符开始搜索" : "没有匹配的对象") }) : null
            ] }) : null,
            view === "actions" && pending ? pending.actions.map((action, index2) => {
              const reason = conflictReason(pending, action, selected, workspaceReferenceCount);
              return /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { id: `agui-mention-action-${action}`, type: "button", role: "option", "aria-selected": index2 === activeIndex, disabled: !!reason || binding, className: cn("flex h-10 w-full items-center justify-between border-l-2 border-l-transparent bg-white px-3 text-left text-xs transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary disabled:opacity-40", index2 === activeIndex && "border-l-primary bg-background-secondary text-primary"), onPointerDown: (event) => event.preventDefault(), onClick: () => void bind(pending, action), children: [
                /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "inline-flex items-center gap-2", children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx(ActionIcon, { action }),
                  ACTION_LABELS[action]
                ] }),
                reason ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "text-[10px] text-muted", children: reason }) : null
              ] }, action);
            }) : null
          ] }),
          error && (candidates.length || view === "actions") ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { role: "alert", className: "border-t border-border px-3 py-2 text-[11px] text-destructive", children: error }) : null
        ]
      }
    );
  });
  function mentionIcon(kind) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx(MentionIcon, { kind });
  }
  function skillQueryAtCursor(value, cursor) {
    if (!value.startsWith("/")) return null;
    const lineEnd = value.indexOf("\n");
    const tokenEnd = lineEnd < 0 ? value.length : lineEnd;
    if (cursor > tokenEnd) return null;
    return {
      start: 0,
      end: lineEnd < 0 ? tokenEnd : tokenEnd + 1,
      query: value.slice(1, tokenEnd)
    };
  }
  const SkillPicker = reactExports.forwardRef(function SkillPicker2({
    open,
    query,
    skills,
    selected,
    onQueryChange,
    onToggle,
    onClose
  }, ref) {
    const [activeIndex, setActiveIndex] = reactExports.useState(0);
    const filtered = reactExports.useMemo(() => {
      const needle = query.trim().toLocaleLowerCase();
      return skills.slice(0, 50).filter(
        (skill) => !needle || skill.name.toLocaleLowerCase().includes(needle) || skill.description.toLocaleLowerCase().includes(needle)
      );
    }, [query, skills]);
    reactExports.useEffect(() => setActiveIndex(0), [query, open]);
    const handleKey = (event) => {
      if (!open || event.nativeEvent.isComposing) return false;
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return true;
      }
      if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        setActiveIndex(event.key === "Home" ? 0 : Math.max(0, filtered.length - 1));
        return true;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        setActiveIndex((value) => filtered.length ? (value + delta + filtered.length) % filtered.length : 0);
        return true;
      }
      if ((event.key === "Enter" || event.key === " ") && filtered[activeIndex]) {
        event.preventDefault();
        onToggle(filtered[activeIndex]);
        return true;
      }
      return false;
    };
    reactExports.useImperativeHandle(ref, () => ({
      handleKey: (event) => handleKey(event)
    }));
    if (!open) return null;
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "agui-picker absolute bottom-full left-0 z-40 mb-2 w-full max-w-md overflow-hidden rounded-md border border-border/70 bg-white text-primary shadow-[0_12px_32px_rgba(15,23,42,0.14)]", role: "dialog", "aria-label": "选择技能", onKeyDown: (event) => handleKey(event), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(PickerSearch, { autoFocus: true, "aria-controls": "agui-skill-options", "aria-expanded": open, value: query, onChange: (event) => {
        onQueryChange(event.target.value);
        setActiveIndex(0);
      }, placeholder: "搜索技能名称或用途", "aria-label": "搜索技能", trailing: /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        "已选 ",
        selected.length,
        "/1"
      ] }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { id: "agui-skill-options", className: "max-h-60 overflow-y-auto p-1", role: "listbox", "aria-label": "技能列表", "aria-activedescendant": filtered[activeIndex] ? `agui-skill-${filtered[activeIndex].id}` : void 0, children: [
        filtered.map((skill, index2) => {
          const checked = selected.some((item) => item.id === skill.id);
          return /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { id: `agui-skill-${skill.id}`, type: "button", role: "option", "aria-selected": checked, title: skill.description, className: cn("flex min-h-11 w-full items-center gap-2 border-l-2 border-l-transparent bg-white px-2 py-1.5 text-left transition-colors duration-150 hover:border-l-primary hover:bg-background-secondary hover:text-primary", index2 === activeIndex && "border-l-primary bg-background-secondary text-primary"), onClick: () => onToggle(skill), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: cn("grid size-5 shrink-0 place-items-center rounded border border-border bg-white", checked && "border-positive bg-positive text-white"), children: checked ? /* @__PURE__ */ jsxRuntimeExports.jsx(Check, { size: 13 }) : /* @__PURE__ */ jsxRuntimeExports.jsx(Sparkles, { size: 12 }) }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "min-w-0 flex-1", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block truncate text-xs", children: skill.name }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block truncate text-[10px] text-muted", children: skill.description })
            ] })
          ] }, skill.id);
        }),
        !filtered.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "px-3 py-5 text-center text-xs text-muted", children: "没有匹配的技能" }) : null
      ] })
    ] });
  });
  const ACCEPTED_TYPES = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "application/pdf": "document",
    "text/plain": "document",
    "text/csv": "document",
    "application/json": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document"
  };
  const MB = 1024 * 1024;
  const MENTION_BOUNDARY = /[\s，。！？；：、（）【】《》“”‘’]/u;
  const MENTION_TERMINATOR = /[\s@，。！？；：、（）【】《》“”‘’]/u;
  function menuQueryAtCursor(value, cursor) {
    const safeCursor = Math.max(0, Math.min(cursor, value.length));
    let at = safeCursor - 1;
    while (at >= 0 && value[at] !== "@" && !MENTION_TERMINATOR.test(value[at])) at -= 1;
    if (at < 0 || value[at] !== "@") return null;
    if (at > 0 && !MENTION_BOUNDARY.test(value[at - 1])) return null;
    let end = safeCursor;
    while (end < value.length && !MENTION_TERMINATOR.test(value[end])) end += 1;
    return { start: at, end, query: value.slice(at + 1, end) };
  }
  function formatSize(size) {
    return size < MB ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / MB).toFixed(1)} MB`;
  }
  function fileBadge(file) {
    var _a;
    const extension2 = (_a = file.name.split(".").pop()) == null ? void 0 : _a.toUpperCase();
    return extension2 && extension2.length <= 4 ? extension2 : "文件";
  }
  function uploadedLabel(template, count) {
    return template.replace("{count}", String(count));
  }
  function fileKind(file) {
    if (file.type === "application/pdf") return "PDF 文档";
    if (file.type.includes("spreadsheet") || file.type.includes("excel") || file.type === "text/csv") return "Excel 表格";
    if (file.type.includes("word")) return "Word 文档";
    if (file.type.startsWith("image/")) return "图片";
    if (file.type.startsWith("text/")) return "文本文件";
    return "文档";
  }
  function ChatInput({
    running,
    disabled = false,
    attachments,
    menuOptions,
    agentSkills = [],
    hostBridge,
    onSend,
    onStop,
    onUpload,
    onRemove,
    labels,
    icons,
    onOpenWorkspace,
    workspaceReferences = [],
    onRemoveWorkspaceReference,
    onMentionsChange
  }) {
    var _a;
    const [value, setValue] = reactExports.useState("");
    const [menuMention, setMenuMention] = reactExports.useState();
    const [mentions, setMentions] = reactExports.useState([]);
    const [menuQuery, setMenuQuery] = reactExports.useState(null);
    const [selectedSkills, setSelectedSkills] = reactExports.useState([]);
    const [skillQuery, setSkillQuery] = reactExports.useState(null);
    const [skillSearch, setSkillSearch] = reactExports.useState("");
    const [skillOpen, setSkillOpen] = reactExports.useState(false);
    const [sending, setSending] = reactExports.useState(false);
    const [activeMenuIndex, setActiveMenuIndex] = reactExports.useState(0);
    const [items, setItems] = reactExports.useState([]);
    const [dragging, setDragging] = reactExports.useState(false);
    const textareaRef = reactExports.useRef(null);
    const formRef = reactExports.useRef(null);
    const mentionPickerRef = reactExports.useRef(null);
    const skillPickerRef = reactExports.useRef(null);
    const inputRef = reactExports.useRef(null);
    const dragDepth = reactExports.useRef(0);
    const unifiedMentions = Boolean((hostBridge == null ? void 0 : hostBridge.searchMentions) && (hostBridge == null ? void 0 : hostBridge.bindMention));
    const config = typeof attachments === "object" ? attachments : {};
    const enabled = attachments !== false && config.enabled !== false;
    const maxFileSize = config.maxFileSize || 10 * MB;
    const maxFiles = config.maxFiles || 5;
    const maxTotalSize = config.maxTotalSize || 25 * MB;
    const normalizedMenuQuery = (menuQuery == null ? void 0 : menuQuery.query.trim().toLocaleLowerCase()) || "";
    const filteredMenus = menuQuery ? menuOptions.filter(
      (option) => !normalizedMenuQuery || option.fullPath.toLocaleLowerCase().includes(normalizedMenuQuery)
    ).slice(0, 8) : [];
    reactExports.useEffect(() => {
      const closeOutside = (event) => {
        var _a2;
        if (!((_a2 = formRef.current) == null ? void 0 : _a2.contains(event.target))) {
          setMenuQuery(null);
          setSkillOpen(false);
        }
      };
      document.addEventListener("pointerdown", closeOutside);
      document.addEventListener("focusin", closeOutside);
      return () => {
        document.removeEventListener("pointerdown", closeOutside);
        document.removeEventListener("focusin", closeOutside);
      };
    }, []);
    reactExports.useEffect(() => {
      setSelectedSkills((current) => {
        const next = current.map((skill) => ({ ...skill, valid: agentSkills.some((option) => option.id === skill.id && option.name === skill.name) }));
        return next.every((skill, index2) => skill.valid === current[index2].valid) ? current : next;
      });
    }, [agentSkills]);
    reactExports.useLayoutEffect(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.style.height = "auto";
      const style = window.getComputedStyle(textarea);
      const lineHeight = Number.parseFloat(style.lineHeight) || 20;
      const maxHeight = lineHeight * 6 + Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
      textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
      textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
    }, [value]);
    const updateItem = (localId, values) => {
      setItems((current) => current.map((item) => item.localId === localId ? { ...item, ...values } : item));
    };
    const addFiles = (files) => {
      if (!enabled || disabled || !files.length) return;
      const next = [];
      let count = items.length;
      let totalSize = items.reduce((sum, item) => sum + item.file.size, 0);
      files.forEach((file) => {
        let error = "";
        if (!ACCEPTED_TYPES[file.type]) error = "不支持的文件类型";
        else if (file.size > maxFileSize) error = `文件超过 ${formatSize(maxFileSize)}`;
        else if (count >= maxFiles) error = `最多添加 ${maxFiles} 个文件`;
        else if (totalSize + file.size > maxTotalSize) error = `附件总大小超过 ${formatSize(maxTotalSize)}`;
        const localId = `${Date.now()}-${Math.random()}`;
        next.push({
          localId,
          file,
          progress: 0,
          status: error ? "error" : "uploading",
          error: error || void 0,
          previewUrl: ACCEPTED_TYPES[file.type] === "image" ? URL.createObjectURL(file) : void 0
        });
        count += 1;
        totalSize += file.size;
      });
      setItems((current) => [...current, ...next]);
      next.filter((item) => item.status === "uploading").forEach((item) => {
        void onUpload(item.file, (progress) => updateItem(item.localId, { progress })).then(
          (attachment) => updateItem(item.localId, { attachment, progress: 100, status: "ready" }),
          (error) => updateItem(item.localId, { error: (error == null ? void 0 : error.message) || "上传失败", status: "error" })
        );
      });
    };
    reactExports.useEffect(() => {
      var _a2;
      if (!enabled || disabled) return;
      const dropRegion = (_a2 = textareaRef.current) == null ? void 0 : _a2.closest("main");
      if (!dropRegion) return;
      const hasFiles = (transfer) => Boolean(transfer && (transfer.files.length || Array.from(transfer.types || []).some((type) => String(type).toLocaleLowerCase() === "files") || Array.from(transfer.items || []).some((item) => item.kind === "file")));
      const filesFrom = (transfer) => {
        if (!transfer) return [];
        const files = Array.from(transfer.files || []);
        Array.from(transfer.items || []).forEach((item) => {
          if (item.kind !== "file") return;
          const file = item.getAsFile();
          if (file && !files.includes(file)) files.push(file);
        });
        return files;
      };
      const dragEnter = (rawEvent) => {
        const event = rawEvent;
        if (!hasFiles(event.dataTransfer)) return;
        event.preventDefault();
        dragDepth.current += 1;
        setDragging(true);
      };
      const dragOver = (rawEvent) => {
        const event = rawEvent;
        if (hasFiles(event.dataTransfer)) event.preventDefault();
      };
      const dragLeave = (rawEvent) => {
        const event = rawEvent;
        if (dragDepth.current === 0) return;
        event.preventDefault();
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragging(false);
      };
      const drop = (rawEvent) => {
        const event = rawEvent;
        const files = filesFrom(event.dataTransfer);
        dragDepth.current = 0;
        setDragging(false);
        if (!files.length) return;
        event.preventDefault();
        addFiles(files);
      };
      dropRegion.addEventListener("dragenter", dragEnter);
      dropRegion.addEventListener("dragover", dragOver);
      dropRegion.addEventListener("dragleave", dragLeave);
      dropRegion.addEventListener("drop", drop);
      return () => {
        dropRegion.removeEventListener("dragenter", dragEnter);
        dropRegion.removeEventListener("dragover", dragOver);
        dropRegion.removeEventListener("dragleave", dragLeave);
        dropRegion.removeEventListener("drop", drop);
      };
    }, [disabled, enabled, items]);
    const removeItem = (item) => {
      setItems((current) => current.filter((candidate) => candidate.localId !== item.localId));
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      if (item.attachment) void onRemove(item.attachment.id);
    };
    const readyAttachments = items.flatMap((item) => item.attachment ? [item.attachment] : []);
    const canSend = !running && !sending && !disabled && !items.some((item) => item.status !== "ready") && (!!value.trim() || readyAttachments.length > 0 || !!menuMention || mentions.length > 0 || selectedSkills.length > 0 || workspaceReferences.length > 0);
    const selectMenu = (option) => {
      if (!menuQuery) return;
      const cursor = menuQuery.start;
      setValue((current) => current.slice(0, menuQuery.start) + current.slice(menuQuery.end));
      setMenuMention({ ...option, path: [...option.path], valid: true });
      setMenuQuery(null);
      setActiveMenuIndex(0);
      window.setTimeout(() => {
        var _a2, _b;
        (_a2 = textareaRef.current) == null ? void 0 : _a2.focus();
        (_b = textareaRef.current) == null ? void 0 : _b.setSelectionRange(cursor, cursor);
      }, 0);
    };
    const selectMention = (reference) => {
      if (!menuQuery) return;
      const cursor = menuQuery.start;
      setValue((current) => current.slice(0, menuQuery.start) + current.slice(menuQuery.end));
      setMentions((current) => {
        const next = [...current, { ...reference }];
        onMentionsChange == null ? void 0 : onMentionsChange(next.length);
        return next;
      });
      setMenuQuery(null);
      window.setTimeout(() => {
        var _a2, _b;
        (_a2 = textareaRef.current) == null ? void 0 : _a2.focus();
        (_b = textareaRef.current) == null ? void 0 : _b.setSelectionRange(cursor, cursor);
      }, 0);
    };
    const toggleSkill = (skill) => {
      setSelectedSkills((current) => {
        if (current.some((item) => item.id === skill.id)) {
          return current.filter((item) => item.id !== skill.id);
        }
        return [{ ...skill, valid: true }];
      });
      setSkillOpen(false);
      if (skillQuery) {
        setValue((current) => current.slice(0, skillQuery.start) + current.slice(skillQuery.end));
        setSkillQuery(null);
        setSkillSearch("");
      }
    };
    const submit = async () => {
      if (!canSend) return;
      const content2 = value.trim();
      const selectedMentions = unifiedMentions ? mentions : menuMention;
      setSending(true);
      let sent = false;
      try {
        sent = await Promise.resolve(selectedSkills.length ? onSend(
          content2,
          readyAttachments,
          selectedMentions || void 0,
          selectedSkills.map((skill) => ({ ...skill })),
          workspaceReferences.map((reference) => ({ ...reference }))
        ) : onSend(content2, readyAttachments, selectedMentions || void 0, void 0, workspaceReferences.map((reference) => ({ ...reference }))));
      } catch (_error) {
        sent = false;
      } finally {
        setSending(false);
      }
      if (sent === false) return;
      setValue("");
      setMenuMention(void 0);
      setMentions([]);
      onMentionsChange == null ? void 0 : onMentionsChange(0);
      setSelectedSkills([]);
      setMenuQuery(null);
      setSkillOpen(false);
      items.forEach((item) => item.previewUrl && URL.revokeObjectURL(item.previewUrl));
      setItems([]);
      window.setTimeout(() => {
        var _a2;
        return (_a2 = textareaRef.current) == null ? void 0 : _a2.focus();
      }, 0);
    };
    const onKeyDown = (event) => {
      var _a2, _b;
      if (skillOpen && ((_a2 = skillPickerRef.current) == null ? void 0 : _a2.handleKey(event))) return;
      if (unifiedMentions && menuQuery && ((_b = mentionPickerRef.current) == null ? void 0 : _b.handleKey(event))) return;
      if (menuQuery) {
        if (event.key === "Escape") {
          event.preventDefault();
          setMenuQuery(null);
          return;
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const direction = event.key === "ArrowDown" ? 1 : -1;
          const length = filteredMenus.length;
          setActiveMenuIndex((current) => length ? (current + direction + length) % length : 0);
          return;
        }
        if (event.key === "Enter" && filteredMenus[activeMenuIndex]) {
          event.preventDefault();
          selectMenu(filteredMenus[activeMenuIndex]);
          return;
        }
      }
      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
        event.preventDefault();
        void submit();
      }
    };
    const onPaste = (event) => {
      if (!enabled) return;
      const files = Array.from(event.clipboardData.files || []);
      Array.from(event.clipboardData.items || []).forEach((item) => {
        if (item.kind !== "file") return;
        const file = item.getAsFile();
        if (file && !files.includes(file)) files.push(file);
      });
      if (!files.length) return;
      event.preventDefault();
      addFiles(files);
    };
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(
      "form",
      {
        ref: formRef,
        className: "relative w-full shrink-0 border border-solid border-border/60 bg-background-panel px-4 pb-3 pt-3 shadow-none sm:px-6",
        onClick: (event) => {
          var _a2;
          const target = event.target;
          if (!target.closest("button, a, input, textarea")) (_a2 = textareaRef.current) == null ? void 0 : _a2.focus();
        },
        onSubmit: (event) => {
          event.preventDefault();
          void submit();
        },
        children: [
          dragging && ((_a = textareaRef.current) == null ? void 0 : _a.closest("main")) ? reactDomExports.createPortal(
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "pointer-events-none absolute inset-0 z-50 grid place-items-center border-2 border-dashed border-primary/30 bg-background-panel/95 text-secondary backdrop-blur-[1px]", "aria-label": "拖放附件", children: /* @__PURE__ */ jsxRuntimeExports.jsx(CloudUpload, { className: "size-6" }) }),
            textareaRef.current.closest("main")
          ) : null,
          items.length ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mb-3", "aria-label": labels.attachments, children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mb-2 flex h-5 items-center justify-between gap-3 text-xs text-muted", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: uploadedLabel(labels.uploadedAttachments, items.length) }),
              /* @__PURE__ */ jsxRuntimeExports.jsxs(
                "button",
                {
                  type: "button",
                  className: "inline-flex h-6 items-center gap-1 rounded border-0 bg-transparent px-1 text-xs text-secondary hover:bg-background-secondary hover:text-primary",
                  "aria-label": labels.clearAttachments,
                  onClick: () => items.forEach(removeItem),
                  children: [
                    /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3" }),
                    labels.clearAttachments
                  ]
                }
              )
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex flex-wrap gap-2", children: items.map((item) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "relative flex h-14 w-52 min-w-0 items-center gap-2 rounded-md border border-border bg-background-panel p-2 pr-7 shadow-[0_1px_2px_rgba(15,23,42,0.03)]", children: [
              item.previewUrl ? /* @__PURE__ */ jsxRuntimeExports.jsx("img", { className: "size-9 shrink-0 rounded object-cover", src: item.previewUrl, alt: "" }) : /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: cn(
                "grid size-9 shrink-0 place-items-center rounded-md border border-border bg-background-secondary text-[9px] font-semibold text-primary",
                (item.file.type.includes("spreadsheet") || item.file.type === "text/csv") && "text-positive"
              ), children: fileBadge(item.file) }),
              /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "min-w-0 flex-1", children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "truncate text-xs font-medium text-primary", title: item.file.name, children: item.file.name }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: cn("mt-0.5 truncate text-[10px] text-muted", item.error && "text-destructive"), children: item.error || (item.status === "uploading" ? `上传中 ${item.progress}%` : `${fileKind(item.file)} · ${formatSize(item.file.size)}`) }),
                item.status === "uploading" ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-1 h-1 overflow-hidden rounded bg-border", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "h-full bg-primary", style: { width: `${item.progress}%` } }) }) : null
              ] }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full border border-solid border-background-panel bg-muted p-0 text-background-panel shadow-sm hover:bg-primary", "aria-label": `${labels.removeAttachment} ${item.file.name}`, onClick: () => removeItem(item), children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3" }) })
            ] }, item.localId)) })
          ] }) : null,
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
            mentions.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex flex-wrap gap-1.5", "aria-label": "已选对象引用", children: mentions.map((mention) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-primary/20 bg-accent px-2 py-1 text-xs text-primary", title: `${mention.detail} · ${ACTION_LABELS[mention.action]}`, children: [
              mentionIcon(mention.kind),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "truncate", children: mention.label }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-5 shrink-0 place-items-center rounded border-0 bg-transparent p-0 text-muted hover:bg-background hover:text-primary", "aria-label": `移除引用 ${mention.label}`, title: "移除引用", onClick: () => setMentions((current) => {
                const next = current.filter((item) => item.id !== mention.id);
                onMentionsChange == null ? void 0 : onMentionsChange(next.length);
                return next;
              }), children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3" }) })
            ] }, mention.id)) }) : null,
            workspaceReferences.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex flex-wrap gap-1.5", "aria-label": "已选工作区引用", children: workspaceReferences.map((reference) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-border bg-background-panel px-2 py-1 text-xs text-primary", title: reference.path, children: [
              reference.isDirectory ? /* @__PURE__ */ jsxRuntimeExports.jsx(Folder, { className: "size-3.5 shrink-0" }) : /* @__PURE__ */ jsxRuntimeExports.jsx(FileText, { className: "size-3.5 shrink-0" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "truncate", children: reference.name }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-5 shrink-0 place-items-center border-0 bg-transparent p-0 text-muted hover:bg-accent hover:text-primary", "aria-label": `移除工作区引用 ${reference.name}`, onClick: () => onRemoveWorkspaceReference == null ? void 0 : onRemoveWorkspaceReference(reference.id), children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3" }) })
            ] }, reference.id)) }) : null,
            selectedSkills.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex flex-wrap gap-1.5", "aria-label": "已选技能", children: selectedSkills.map((skill) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-border bg-background-panel px-2 py-1 text-xs text-primary", title: skill.valid ? skill.description : "技能已不可用，请移除后重试", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(Sparkles, { className: "size-3.5 shrink-0" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "truncate", children: skill.name }),
              !skill.valid ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0 text-destructive", children: "（不可用）" }) : null,
              /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-5 shrink-0 place-items-center border-0 bg-transparent p-0 text-muted hover:bg-accent", "aria-label": `移除技能 ${skill.name}`, onClick: () => setSelectedSkills((current) => current.filter((item) => item.id !== skill.id)), children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3" }) })
            ] }, skill.id)) }) : null,
            menuMention ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex items-center", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "inline-flex max-w-full items-center gap-1.5 rounded-md border border-primary/20 bg-accent px-2 py-1 text-xs text-primary", title: menuMention.fullPath, children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(AtSign, { className: "size-3.5 shrink-0" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "truncate", children: menuMention.fullPath }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-5 shrink-0 place-items-center rounded border-0 bg-transparent p-0 text-muted hover:bg-background hover:text-primary", "aria-label": "移除菜单", title: "移除菜单", onClick: () => setMenuMention(void 0), children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3" }) })
            ] }) }) : null,
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "relative", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("textarea", { ref: textareaRef, rows: 1, disabled: disabled || sending, className: "block min-h-11 w-full resize-none rounded-lg border-0 bg-background-secondary px-3 py-3 text-sm leading-5 text-primary outline outline-1 outline-transparent transition-[border-color,background-color,outline-color,box-shadow] placeholder:text-muted/90 focus:bg-background focus:outline-primary/15 focus:shadow-[0_0_0_3px_rgba(59,130,246,0.06)] disabled:cursor-not-allowed disabled:opacity-45", placeholder: labels.inputPlaceholder, value, onChange: (event) => {
                const nextValue = event.target.value;
                const cursor = event.target.selectionStart ?? nextValue.length;
                const nextSkillQuery = skillQueryAtCursor(nextValue, cursor);
                setValue(nextValue);
                setActiveMenuIndex(0);
                if (nextSkillQuery && agentSkills.length) {
                  setSkillQuery(nextSkillQuery);
                  setSkillSearch(nextSkillQuery.query);
                  setSkillOpen(true);
                  setMenuQuery(null);
                } else {
                  setSkillQuery(null);
                  const nextMention = menuQueryAtCursor(nextValue, cursor);
                  setMenuQuery(nextMention);
                  if (nextMention) setSkillOpen(false);
                }
              }, onClick: (event) => {
                const cursor = event.currentTarget.selectionStart ?? value.length;
                const nextSkill = skillQueryAtCursor(value, cursor);
                if (nextSkill && agentSkills.length) {
                  setSkillQuery(nextSkill);
                  setSkillSearch(nextSkill.query);
                  setSkillOpen(true);
                  setMenuQuery(null);
                } else {
                  setMenuQuery(menuQueryAtCursor(value, cursor));
                }
              }, onKeyDown, onPasteCapture: onPaste, "aria-autocomplete": "list", "aria-expanded": Boolean(menuQuery || skillOpen), "aria-controls": skillOpen ? "agui-skill-options" : menuQuery ? "agui-mention-options" : void 0 }),
              unifiedMentions && menuQuery && hostBridge ? /* @__PURE__ */ jsxRuntimeExports.jsx(MentionPicker, { ref: mentionPickerRef, open: true, query: menuQuery, selected: mentions, workspaceReferenceCount: workspaceReferences.length, hostBridge, onSelect: selectMention, onOpenSkills: () => {
                const cursor = menuQuery.start;
                setValue((current) => current.slice(0, menuQuery.start) + current.slice(menuQuery.end));
                setMenuQuery(null);
                setSkillQuery(null);
                setSkillSearch(String());
                setSkillOpen(true);
                window.setTimeout(() => {
                  var _a2;
                  return (_a2 = textareaRef.current) == null ? void 0 : _a2.setSelectionRange(cursor, cursor);
                }, 0);
              }, onClose: () => setMenuQuery(null) }) : null,
              !unifiedMentions && menuQuery ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { role: "listbox", className: "absolute bottom-full left-0 right-0 z-40 mb-1 max-h-72 overflow-y-auto rounded-md border border-border bg-background-panel p-1 shadow-lg", children: filteredMenus.length ? filteredMenus.map((option, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { type: "button", role: "option", "aria-selected": index2 === activeMenuIndex, className: cn("flex w-full items-center gap-2 rounded border-0 bg-transparent px-2.5 py-2 text-left text-xs text-secondary hover:bg-accent", index2 === activeMenuIndex && "bg-accent text-primary"), onPointerDown: (event) => event.preventDefault(), onClick: () => selectMenu(option), children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx(AtSign, { className: "size-3.5 shrink-0 text-muted" }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "min-w-0 flex-1 truncate", title: option.fullPath, children: option.fullPath })
              ] }, option.menuId)) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "px-2.5 py-2 text-xs text-muted", children: "没有匹配的菜单" }) }) : null,
              /* @__PURE__ */ jsxRuntimeExports.jsx(SkillPicker, { ref: skillPickerRef, open: skillOpen && agentSkills.length > 0, query: skillSearch, skills: agentSkills, selected: selectedSkills, onQueryChange: setSkillSearch, onToggle: toggleSkill, onClose: () => {
                setSkillOpen(false);
                setSkillQuery(null);
              } })
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-2 flex min-h-8 items-center justify-between gap-2", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex items-center gap-1", children: [
                enabled ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsx("input", { ref: inputRef, className: "hidden", type: "file", disabled, multiple: true, accept: Object.keys(ACCEPTED_TYPES).join(","), onChange: (event) => {
                    addFiles(Array.from(event.target.files || []));
                    event.target.value = "";
                  } }),
                  /* @__PURE__ */ jsxRuntimeExports.jsx(Button, { type: "button", variant: "ghost", size: "icon", disabled, className: "size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:border-primary/20 hover:bg-accent", "aria-label": labels.addAttachments, title: labels.addAttachments, onClick: () => {
                    var _a2;
                    return (_a2 = inputRef.current) == null ? void 0 : _a2.click();
                  }, children: icons.upload })
                ] }) : null,
                agentSkills.length ? /* @__PURE__ */ jsxRuntimeExports.jsx(Button, { type: "button", variant: "ghost", size: "icon", disabled: disabled || sending, className: cn("size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:bg-accent", skillOpen && "bg-accent text-primary"), "aria-label": "选择技能", title: "选择技能", "aria-pressed": skillOpen, onClick: () => {
                  setSkillOpen((current) => !current);
                  setSkillQuery(null);
                  setSkillSearch("");
                  setMenuQuery(null);
                }, children: /* @__PURE__ */ jsxRuntimeExports.jsx(Sparkles, { className: "size-4" }) }) : null,
                onOpenWorkspace ? /* @__PURE__ */ jsxRuntimeExports.jsx(Button, { type: "button", variant: "ghost", size: "icon", disabled, className: "size-8 shrink-0 rounded-md border-border bg-background-panel text-secondary shadow-none hover:bg-accent", "aria-label": "打开工作区", title: "打开工作区", onClick: onOpenWorkspace, children: /* @__PURE__ */ jsxRuntimeExports.jsx(FolderOpen, { className: "size-4" }) }) : null
              ] }),
              /* @__PURE__ */ jsxRuntimeExports.jsx(Button, { type: running ? "button" : "submit", variant: "primary", size: "icon", className: cn("size-8 shrink-0 rounded-md shadow-none disabled:border-border disabled:bg-border disabled:text-muted", running && "ring-1 ring-primary/15"), disabled: running ? false : disabled || !canSend, "aria-label": running ? labels.stopGenerating : labels.sendMessage, title: running ? labels.stopGenerating : labels.sendMessage, onClick: running ? onStop : void 0, children: running ? icons.stop : icons.send })
            ] })
          ] })
        ]
      }
    );
  }
  function ok$1() {
  }
  function unreachable() {
  }
  function stringify$1(values, options) {
    const settings = {};
    const input = values[values.length - 1] === "" ? [...values, ""] : values;
    return input.join(
      (settings.padRight ? " " : "") + "," + (settings.padLeft === false ? "" : " ")
    ).trim();
  }
  const nameRe = /^[$_\p{ID_Start}][$_\u{200C}\u{200D}\p{ID_Continue}]*$/u;
  const nameReJsx = /^[$_\p{ID_Start}][-$_\u{200C}\u{200D}\p{ID_Continue}]*$/u;
  const emptyOptions$3 = {};
  function name(name2, options) {
    const settings = emptyOptions$3;
    const re2 = settings.jsx ? nameReJsx : nameRe;
    return re2.test(name2);
  }
  const re = /[ \t\n\f\r]/g;
  function whitespace(thing) {
    return typeof thing === "object" ? thing.type === "text" ? empty$1(thing.value) : false : empty$1(thing);
  }
  function empty$1(value) {
    return value.replace(re, "") === "";
  }
  class Schema {
    /**
     * @param {SchemaType['property']} property
     *   Property.
     * @param {SchemaType['normal']} normal
     *   Normal.
     * @param {Space | undefined} [space]
     *   Space.
     * @returns
     *   Schema.
     */
    constructor(property, normal, space2) {
      this.normal = normal;
      this.property = property;
      if (space2) {
        this.space = space2;
      }
    }
  }
  Schema.prototype.normal = {};
  Schema.prototype.property = {};
  Schema.prototype.space = void 0;
  function merge(definitions, space2) {
    const property = {};
    const normal = {};
    for (const definition2 of definitions) {
      Object.assign(property, definition2.property);
      Object.assign(normal, definition2.normal);
    }
    return new Schema(property, normal, space2);
  }
  function normalize$1(value) {
    return value.toLowerCase();
  }
  class Info {
    /**
     * @param {string} property
     *   Property.
     * @param {string} attribute
     *   Attribute.
     * @returns
     *   Info.
     */
    constructor(property, attribute) {
      this.attribute = attribute;
      this.property = property;
    }
  }
  Info.prototype.attribute = "";
  Info.prototype.booleanish = false;
  Info.prototype.boolean = false;
  Info.prototype.commaOrSpaceSeparated = false;
  Info.prototype.commaSeparated = false;
  Info.prototype.defined = false;
  Info.prototype.mustUseProperty = false;
  Info.prototype.number = false;
  Info.prototype.overloadedBoolean = false;
  Info.prototype.property = "";
  Info.prototype.spaceSeparated = false;
  Info.prototype.space = void 0;
  let powers = 0;
  const boolean = increment();
  const booleanish = increment();
  const overloadedBoolean = increment();
  const number = increment();
  const spaceSeparated = increment();
  const commaSeparated = increment();
  const commaOrSpaceSeparated = increment();
  function increment() {
    return 2 ** ++powers;
  }
  const types = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
    __proto__: null,
    boolean,
    booleanish,
    commaOrSpaceSeparated,
    commaSeparated,
    number,
    overloadedBoolean,
    spaceSeparated
  }, Symbol.toStringTag, { value: "Module" }));
  const checks = (
    /** @type {ReadonlyArray<keyof typeof types>} */
    Object.keys(types)
  );
  class DefinedInfo extends Info {
    /**
     * @constructor
     * @param {string} property
     *   Property.
     * @param {string} attribute
     *   Attribute.
     * @param {number | null | undefined} [mask]
     *   Mask.
     * @param {Space | undefined} [space]
     *   Space.
     * @returns
     *   Info.
     */
    constructor(property, attribute, mask, space2) {
      let index2 = -1;
      super(property, attribute);
      mark(this, "space", space2);
      if (typeof mask === "number") {
        while (++index2 < checks.length) {
          const check = checks[index2];
          mark(this, checks[index2], (mask & types[check]) === types[check]);
        }
      }
    }
  }
  DefinedInfo.prototype.defined = true;
  function mark(values, key, value) {
    if (value) {
      values[key] = value;
    }
  }
  function create(definition2) {
    const properties = {};
    const normals = {};
    for (const [property, value] of Object.entries(definition2.properties)) {
      const info = new DefinedInfo(
        property,
        definition2.transform(definition2.attributes || {}, property),
        value,
        definition2.space
      );
      if (definition2.mustUseProperty && definition2.mustUseProperty.includes(property)) {
        info.mustUseProperty = true;
      }
      properties[property] = info;
      normals[normalize$1(property)] = property;
      normals[normalize$1(info.attribute)] = property;
    }
    return new Schema(properties, normals, definition2.space);
  }
  const aria = create({
    properties: {
      ariaActiveDescendant: null,
      ariaAtomic: booleanish,
      ariaAutoComplete: null,
      ariaBusy: booleanish,
      ariaChecked: booleanish,
      ariaColCount: number,
      ariaColIndex: number,
      ariaColSpan: number,
      ariaControls: spaceSeparated,
      ariaCurrent: null,
      ariaDescribedBy: spaceSeparated,
      ariaDetails: null,
      ariaDisabled: booleanish,
      ariaDropEffect: spaceSeparated,
      ariaErrorMessage: null,
      ariaExpanded: booleanish,
      ariaFlowTo: spaceSeparated,
      ariaGrabbed: booleanish,
      ariaHasPopup: null,
      ariaHidden: booleanish,
      ariaInvalid: null,
      ariaKeyShortcuts: null,
      ariaLabel: null,
      ariaLabelledBy: spaceSeparated,
      ariaLevel: number,
      ariaLive: null,
      ariaModal: booleanish,
      ariaMultiLine: booleanish,
      ariaMultiSelectable: booleanish,
      ariaOrientation: null,
      ariaOwns: spaceSeparated,
      ariaPlaceholder: null,
      ariaPosInSet: number,
      ariaPressed: booleanish,
      ariaReadOnly: booleanish,
      ariaRelevant: null,
      ariaRequired: booleanish,
      ariaRoleDescription: spaceSeparated,
      ariaRowCount: number,
      ariaRowIndex: number,
      ariaRowSpan: number,
      ariaSelected: booleanish,
      ariaSetSize: number,
      ariaSort: null,
      ariaValueMax: number,
      ariaValueMin: number,
      ariaValueNow: number,
      ariaValueText: null,
      role: null
    },
    transform(_, property) {
      return property === "role" ? property : "aria-" + property.slice(4).toLowerCase();
    }
  });
  function caseSensitiveTransform(attributes, attribute) {
    return attribute in attributes ? attributes[attribute] : attribute;
  }
  function caseInsensitiveTransform(attributes, property) {
    return caseSensitiveTransform(attributes, property.toLowerCase());
  }
  const html$3 = create({
    attributes: {
      acceptcharset: "accept-charset",
      classname: "class",
      htmlfor: "for",
      httpequiv: "http-equiv"
    },
    mustUseProperty: ["checked", "multiple", "muted", "selected"],
    properties: {
      // Standard Properties.
      abbr: null,
      accept: commaSeparated,
      acceptCharset: spaceSeparated,
      accessKey: spaceSeparated,
      action: null,
      allow: null,
      allowFullScreen: boolean,
      allowPaymentRequest: boolean,
      allowUserMedia: boolean,
      alpha: boolean,
      alt: null,
      as: null,
      async: boolean,
      autoCapitalize: null,
      autoComplete: spaceSeparated,
      autoFocus: boolean,
      autoPlay: boolean,
      blocking: spaceSeparated,
      capture: null,
      charSet: null,
      checked: boolean,
      cite: null,
      className: spaceSeparated,
      closedBy: null,
      colorSpace: null,
      cols: number,
      colSpan: number,
      command: null,
      commandFor: null,
      content: null,
      contentEditable: booleanish,
      controls: boolean,
      controlsList: spaceSeparated,
      coords: number | commaSeparated,
      crossOrigin: null,
      data: null,
      dateTime: null,
      decoding: null,
      default: boolean,
      defer: boolean,
      dir: null,
      dirName: null,
      disabled: boolean,
      download: overloadedBoolean,
      draggable: booleanish,
      encType: null,
      enterKeyHint: null,
      fetchPriority: null,
      form: null,
      formAction: null,
      formEncType: null,
      formMethod: null,
      formNoValidate: boolean,
      formTarget: null,
      headers: spaceSeparated,
      height: number,
      hidden: overloadedBoolean,
      high: number,
      href: null,
      hrefLang: null,
      htmlFor: spaceSeparated,
      httpEquiv: spaceSeparated,
      id: null,
      imageSizes: null,
      imageSrcSet: null,
      inert: boolean,
      inputMode: null,
      integrity: null,
      is: null,
      isMap: boolean,
      itemId: null,
      itemProp: spaceSeparated,
      itemRef: spaceSeparated,
      itemScope: boolean,
      itemType: spaceSeparated,
      kind: null,
      label: null,
      lang: null,
      language: null,
      list: null,
      loading: null,
      loop: boolean,
      low: number,
      manifest: null,
      max: null,
      maxLength: number,
      media: null,
      method: null,
      min: null,
      minLength: number,
      multiple: boolean,
      muted: boolean,
      name: null,
      nonce: null,
      noModule: boolean,
      noValidate: boolean,
      onAbort: null,
      onAfterPrint: null,
      onAuxClick: null,
      onBeforeMatch: null,
      onBeforePrint: null,
      onBeforeToggle: null,
      onBeforeUnload: null,
      onBlur: null,
      onCancel: null,
      onCanPlay: null,
      onCanPlayThrough: null,
      onChange: null,
      onClick: null,
      onClose: null,
      onContextLost: null,
      onContextMenu: null,
      onContextRestored: null,
      onCopy: null,
      onCueChange: null,
      onCut: null,
      onDblClick: null,
      onDrag: null,
      onDragEnd: null,
      onDragEnter: null,
      onDragExit: null,
      onDragLeave: null,
      onDragOver: null,
      onDragStart: null,
      onDrop: null,
      onDurationChange: null,
      onEmptied: null,
      onEnded: null,
      onError: null,
      onFocus: null,
      onFormData: null,
      onHashChange: null,
      onInput: null,
      onInvalid: null,
      onKeyDown: null,
      onKeyPress: null,
      onKeyUp: null,
      onLanguageChange: null,
      onLoad: null,
      onLoadedData: null,
      onLoadedMetadata: null,
      onLoadEnd: null,
      onLoadStart: null,
      onMessage: null,
      onMessageError: null,
      onMouseDown: null,
      onMouseEnter: null,
      onMouseLeave: null,
      onMouseMove: null,
      onMouseOut: null,
      onMouseOver: null,
      onMouseUp: null,
      onOffline: null,
      onOnline: null,
      onPageHide: null,
      onPageShow: null,
      onPaste: null,
      onPause: null,
      onPlay: null,
      onPlaying: null,
      onPopState: null,
      onProgress: null,
      onRateChange: null,
      onRejectionHandled: null,
      onReset: null,
      onResize: null,
      onScroll: null,
      onScrollEnd: null,
      onSecurityPolicyViolation: null,
      onSeeked: null,
      onSeeking: null,
      onSelect: null,
      onSlotChange: null,
      onStalled: null,
      onStorage: null,
      onSubmit: null,
      onSuspend: null,
      onTimeUpdate: null,
      onToggle: null,
      onUnhandledRejection: null,
      onUnload: null,
      onVolumeChange: null,
      onWaiting: null,
      onWheel: null,
      open: boolean,
      optimum: number,
      pattern: null,
      ping: spaceSeparated,
      placeholder: null,
      playsInline: boolean,
      popover: null,
      popoverTarget: null,
      popoverTargetAction: null,
      poster: null,
      preload: null,
      readOnly: boolean,
      referrerPolicy: null,
      rel: spaceSeparated,
      required: boolean,
      reversed: boolean,
      rows: number,
      rowSpan: number,
      sandbox: spaceSeparated,
      scope: null,
      scoped: boolean,
      seamless: boolean,
      selected: boolean,
      shadowRootClonable: boolean,
      shadowRootCustomElementRegistry: boolean,
      shadowRootDelegatesFocus: boolean,
      shadowRootMode: null,
      shadowRootSerializable: boolean,
      shape: null,
      size: number,
      sizes: null,
      slot: null,
      span: number,
      spellCheck: booleanish,
      src: null,
      srcDoc: null,
      srcLang: null,
      srcSet: null,
      start: number,
      step: null,
      style: null,
      tabIndex: number,
      target: null,
      title: null,
      translate: null,
      type: null,
      typeMustMatch: boolean,
      useMap: null,
      value: booleanish,
      width: number,
      wrap: null,
      writingSuggestions: null,
      // Legacy.
      // See: https://html.spec.whatwg.org/#other-elements,-attributes-and-apis
      align: null,
      // Several. Use CSS `text-align` instead,
      aLink: null,
      // `<body>`. Use CSS `a:active {color}` instead
      archive: spaceSeparated,
      // `<object>`. List of URIs to archives
      axis: null,
      // `<td>` and `<th>`. Use `scope` on `<th>`
      background: null,
      // `<body>`. Use CSS `background-image` instead
      bgColor: null,
      // `<body>` and table elements. Use CSS `background-color` instead
      border: number,
      // `<table>`. Use CSS `border-width` instead,
      borderColor: null,
      // `<table>`. Use CSS `border-color` instead,
      bottomMargin: number,
      // `<body>`
      cellPadding: null,
      // `<table>`
      cellSpacing: null,
      // `<table>`
      char: null,
      // Several table elements. When `align=char`, sets the character to align on
      charOff: null,
      // Several table elements. When `char`, offsets the alignment
      classId: null,
      // `<object>`
      clear: null,
      // `<br>`. Use CSS `clear` instead
      code: null,
      // `<object>`
      codeBase: null,
      // `<object>`
      codeType: null,
      // `<object>`
      color: null,
      // `<font>` and `<hr>`. Use CSS instead
      compact: boolean,
      // Lists. Use CSS to reduce space between items instead
      declare: boolean,
      // `<object>`
      event: null,
      // `<script>`
      face: null,
      // `<font>`. Use CSS instead
      frame: null,
      // `<table>`
      frameBorder: null,
      // `<iframe>`. Use CSS `border` instead
      hSpace: number,
      // `<img>` and `<object>`
      leftMargin: number,
      // `<body>`
      link: null,
      // `<body>`. Use CSS `a:link {color: *}` instead
      longDesc: null,
      // `<frame>`, `<iframe>`, and `<img>`. Use an `<a>`
      lowSrc: null,
      // `<img>`. Use a `<picture>`
      marginHeight: number,
      // `<body>`
      marginWidth: number,
      // `<body>`
      noResize: boolean,
      // `<frame>`
      noHref: boolean,
      // `<area>`. Use no href instead of an explicit `nohref`
      noShade: boolean,
      // `<hr>`. Use background-color and height instead of borders
      noWrap: boolean,
      // `<td>` and `<th>`
      object: null,
      // `<applet>`
      profile: null,
      // `<head>`
      prompt: null,
      // `<isindex>`
      rev: null,
      // `<link>`
      rightMargin: number,
      // `<body>`
      rules: null,
      // `<table>`
      scheme: null,
      // `<meta>`
      scrolling: booleanish,
      // `<frame>`. Use overflow in the child context
      standby: null,
      // `<object>`
      summary: null,
      // `<table>`
      text: null,
      // `<body>`. Use CSS `color` instead
      topMargin: number,
      // `<body>`
      valueType: null,
      // `<param>`
      version: null,
      // `<html>`. Use a doctype.
      vAlign: null,
      // Several. Use CSS `vertical-align` instead
      vLink: null,
      // `<body>`. Use CSS `a:visited {color}` instead
      vSpace: number,
      // `<img>` and `<object>`
      // Non-standard Properties.
      allowTransparency: null,
      autoCorrect: null,
      autoSave: null,
      credentialless: boolean,
      disablePictureInPicture: boolean,
      disableRemotePlayback: boolean,
      exportParts: commaSeparated,
      part: spaceSeparated,
      prefix: null,
      property: null,
      results: number,
      security: null,
      unselectable: null
    },
    space: "html",
    transform: caseInsensitiveTransform
  });
  const svg$1 = create({
    attributes: {
      accentHeight: "accent-height",
      alignmentBaseline: "alignment-baseline",
      arabicForm: "arabic-form",
      baselineShift: "baseline-shift",
      capHeight: "cap-height",
      className: "class",
      clipPath: "clip-path",
      clipRule: "clip-rule",
      colorInterpolation: "color-interpolation",
      colorInterpolationFilters: "color-interpolation-filters",
      colorProfile: "color-profile",
      colorRendering: "color-rendering",
      crossOrigin: "crossorigin",
      dataType: "datatype",
      dominantBaseline: "dominant-baseline",
      enableBackground: "enable-background",
      fillOpacity: "fill-opacity",
      fillRule: "fill-rule",
      floodColor: "flood-color",
      floodOpacity: "flood-opacity",
      fontFamily: "font-family",
      fontSize: "font-size",
      fontSizeAdjust: "font-size-adjust",
      fontStretch: "font-stretch",
      fontStyle: "font-style",
      fontVariant: "font-variant",
      fontWeight: "font-weight",
      glyphName: "glyph-name",
      glyphOrientationHorizontal: "glyph-orientation-horizontal",
      glyphOrientationVertical: "glyph-orientation-vertical",
      hrefLang: "hreflang",
      horizAdvX: "horiz-adv-x",
      horizOriginX: "horiz-origin-x",
      horizOriginY: "horiz-origin-y",
      imageRendering: "image-rendering",
      letterSpacing: "letter-spacing",
      lightingColor: "lighting-color",
      markerEnd: "marker-end",
      markerMid: "marker-mid",
      markerStart: "marker-start",
      maskType: "mask-type",
      navDown: "nav-down",
      navDownLeft: "nav-down-left",
      navDownRight: "nav-down-right",
      navLeft: "nav-left",
      navNext: "nav-next",
      navPrev: "nav-prev",
      navRight: "nav-right",
      navUp: "nav-up",
      navUpLeft: "nav-up-left",
      navUpRight: "nav-up-right",
      onAbort: "onabort",
      onActivate: "onactivate",
      onAfterPrint: "onafterprint",
      onBeforePrint: "onbeforeprint",
      onBegin: "onbegin",
      onCancel: "oncancel",
      onCanPlay: "oncanplay",
      onCanPlayThrough: "oncanplaythrough",
      onChange: "onchange",
      onClick: "onclick",
      onClose: "onclose",
      onCopy: "oncopy",
      onCueChange: "oncuechange",
      onCut: "oncut",
      onDblClick: "ondblclick",
      onDrag: "ondrag",
      onDragEnd: "ondragend",
      onDragEnter: "ondragenter",
      onDragExit: "ondragexit",
      onDragLeave: "ondragleave",
      onDragOver: "ondragover",
      onDragStart: "ondragstart",
      onDrop: "ondrop",
      onDurationChange: "ondurationchange",
      onEmptied: "onemptied",
      onEnd: "onend",
      onEnded: "onended",
      onError: "onerror",
      onFocus: "onfocus",
      onFocusIn: "onfocusin",
      onFocusOut: "onfocusout",
      onHashChange: "onhashchange",
      onInput: "oninput",
      onInvalid: "oninvalid",
      onKeyDown: "onkeydown",
      onKeyPress: "onkeypress",
      onKeyUp: "onkeyup",
      onLoad: "onload",
      onLoadedData: "onloadeddata",
      onLoadedMetadata: "onloadedmetadata",
      onLoadStart: "onloadstart",
      onMessage: "onmessage",
      onMouseDown: "onmousedown",
      onMouseEnter: "onmouseenter",
      onMouseLeave: "onmouseleave",
      onMouseMove: "onmousemove",
      onMouseOut: "onmouseout",
      onMouseOver: "onmouseover",
      onMouseUp: "onmouseup",
      onMouseWheel: "onmousewheel",
      onOffline: "onoffline",
      onOnline: "ononline",
      onPageHide: "onpagehide",
      onPageShow: "onpageshow",
      onPaste: "onpaste",
      onPause: "onpause",
      onPlay: "onplay",
      onPlaying: "onplaying",
      onPopState: "onpopstate",
      onProgress: "onprogress",
      onRateChange: "onratechange",
      onRepeat: "onrepeat",
      onReset: "onreset",
      onResize: "onresize",
      onScroll: "onscroll",
      onSeeked: "onseeked",
      onSeeking: "onseeking",
      onSelect: "onselect",
      onShow: "onshow",
      onStalled: "onstalled",
      onStorage: "onstorage",
      onSubmit: "onsubmit",
      onSuspend: "onsuspend",
      onTimeUpdate: "ontimeupdate",
      onToggle: "ontoggle",
      onUnload: "onunload",
      onVolumeChange: "onvolumechange",
      onWaiting: "onwaiting",
      onZoom: "onzoom",
      overlinePosition: "overline-position",
      overlineThickness: "overline-thickness",
      paintOrder: "paint-order",
      panose1: "panose-1",
      pointerEvents: "pointer-events",
      referrerPolicy: "referrerpolicy",
      renderingIntent: "rendering-intent",
      shapeRendering: "shape-rendering",
      stopColor: "stop-color",
      stopOpacity: "stop-opacity",
      strikethroughPosition: "strikethrough-position",
      strikethroughThickness: "strikethrough-thickness",
      strokeDashArray: "stroke-dasharray",
      strokeDashOffset: "stroke-dashoffset",
      strokeLineCap: "stroke-linecap",
      strokeLineJoin: "stroke-linejoin",
      strokeMiterLimit: "stroke-miterlimit",
      strokeOpacity: "stroke-opacity",
      strokeWidth: "stroke-width",
      tabIndex: "tabindex",
      textAnchor: "text-anchor",
      textDecoration: "text-decoration",
      textRendering: "text-rendering",
      transformOrigin: "transform-origin",
      typeOf: "typeof",
      underlinePosition: "underline-position",
      underlineThickness: "underline-thickness",
      unicodeBidi: "unicode-bidi",
      unicodeRange: "unicode-range",
      unitsPerEm: "units-per-em",
      vAlphabetic: "v-alphabetic",
      vHanging: "v-hanging",
      vIdeographic: "v-ideographic",
      vMathematical: "v-mathematical",
      vectorEffect: "vector-effect",
      vertAdvY: "vert-adv-y",
      vertOriginX: "vert-origin-x",
      vertOriginY: "vert-origin-y",
      wordSpacing: "word-spacing",
      writingMode: "writing-mode",
      xHeight: "x-height",
      // These were camelcased in Tiny. Now lowercased in SVG 2
      playbackOrder: "playbackorder",
      timelineBegin: "timelinebegin"
    },
    properties: {
      about: commaOrSpaceSeparated,
      accentHeight: number,
      accumulate: null,
      additive: null,
      alignmentBaseline: null,
      alphabetic: number,
      amplitude: number,
      arabicForm: null,
      ascent: number,
      attributeName: null,
      attributeType: null,
      azimuth: number,
      bandwidth: null,
      baselineShift: null,
      baseFrequency: null,
      baseProfile: null,
      bbox: null,
      begin: null,
      bias: number,
      by: null,
      calcMode: null,
      capHeight: number,
      className: spaceSeparated,
      clip: null,
      clipPath: null,
      clipPathUnits: null,
      clipRule: null,
      color: null,
      colorInterpolation: null,
      colorInterpolationFilters: null,
      colorProfile: null,
      colorRendering: null,
      content: null,
      contentScriptType: null,
      contentStyleType: null,
      crossOrigin: null,
      cursor: null,
      cx: null,
      cy: null,
      d: null,
      dataType: null,
      defaultAction: null,
      descent: number,
      diffuseConstant: number,
      direction: null,
      display: null,
      dur: null,
      divisor: number,
      dominantBaseline: null,
      download: boolean,
      dx: null,
      dy: null,
      edgeMode: null,
      editable: null,
      elevation: number,
      enableBackground: null,
      end: null,
      event: null,
      exponent: number,
      externalResourcesRequired: null,
      fill: null,
      fillOpacity: number,
      fillRule: null,
      filter: null,
      filterRes: null,
      filterUnits: null,
      floodColor: null,
      floodOpacity: null,
      focusable: null,
      focusHighlight: null,
      fontFamily: null,
      fontSize: null,
      fontSizeAdjust: null,
      fontStretch: null,
      fontStyle: null,
      fontVariant: null,
      fontWeight: null,
      format: null,
      fr: null,
      from: null,
      fx: null,
      fy: null,
      g1: commaSeparated,
      g2: commaSeparated,
      glyphName: commaSeparated,
      glyphOrientationHorizontal: null,
      glyphOrientationVertical: null,
      glyphRef: null,
      gradientTransform: null,
      gradientUnits: null,
      handler: null,
      hanging: number,
      hatchContentUnits: null,
      hatchUnits: null,
      height: null,
      href: null,
      hrefLang: null,
      horizAdvX: number,
      horizOriginX: number,
      horizOriginY: number,
      id: null,
      ideographic: number,
      imageRendering: null,
      initialVisibility: null,
      in: null,
      in2: null,
      intercept: number,
      k: number,
      k1: number,
      k2: number,
      k3: number,
      k4: number,
      kernelMatrix: commaOrSpaceSeparated,
      kernelUnitLength: null,
      keyPoints: null,
      // SEMI_COLON_SEPARATED
      keySplines: null,
      // SEMI_COLON_SEPARATED
      keyTimes: null,
      // SEMI_COLON_SEPARATED
      kerning: null,
      lang: null,
      lengthAdjust: null,
      letterSpacing: null,
      lightingColor: null,
      limitingConeAngle: number,
      local: null,
      markerEnd: null,
      markerMid: null,
      markerStart: null,
      markerHeight: null,
      markerUnits: null,
      markerWidth: null,
      mask: null,
      maskContentUnits: null,
      maskType: null,
      maskUnits: null,
      mathematical: null,
      max: null,
      media: null,
      mediaCharacterEncoding: null,
      mediaContentEncodings: null,
      mediaSize: number,
      mediaTime: null,
      method: null,
      min: null,
      mode: null,
      name: null,
      navDown: null,
      navDownLeft: null,
      navDownRight: null,
      navLeft: null,
      navNext: null,
      navPrev: null,
      navRight: null,
      navUp: null,
      navUpLeft: null,
      navUpRight: null,
      numOctaves: null,
      observer: null,
      offset: null,
      onAbort: null,
      onActivate: null,
      onAfterPrint: null,
      onBeforePrint: null,
      onBegin: null,
      onCancel: null,
      onCanPlay: null,
      onCanPlayThrough: null,
      onChange: null,
      onClick: null,
      onClose: null,
      onCopy: null,
      onCueChange: null,
      onCut: null,
      onDblClick: null,
      onDrag: null,
      onDragEnd: null,
      onDragEnter: null,
      onDragExit: null,
      onDragLeave: null,
      onDragOver: null,
      onDragStart: null,
      onDrop: null,
      onDurationChange: null,
      onEmptied: null,
      onEnd: null,
      onEnded: null,
      onError: null,
      onFocus: null,
      onFocusIn: null,
      onFocusOut: null,
      onHashChange: null,
      onInput: null,
      onInvalid: null,
      onKeyDown: null,
      onKeyPress: null,
      onKeyUp: null,
      onLoad: null,
      onLoadedData: null,
      onLoadedMetadata: null,
      onLoadStart: null,
      onMessage: null,
      onMouseDown: null,
      onMouseEnter: null,
      onMouseLeave: null,
      onMouseMove: null,
      onMouseOut: null,
      onMouseOver: null,
      onMouseUp: null,
      onMouseWheel: null,
      onOffline: null,
      onOnline: null,
      onPageHide: null,
      onPageShow: null,
      onPaste: null,
      onPause: null,
      onPlay: null,
      onPlaying: null,
      onPopState: null,
      onProgress: null,
      onRateChange: null,
      onRepeat: null,
      onReset: null,
      onResize: null,
      onScroll: null,
      onSeeked: null,
      onSeeking: null,
      onSelect: null,
      onShow: null,
      onStalled: null,
      onStorage: null,
      onSubmit: null,
      onSuspend: null,
      onTimeUpdate: null,
      onToggle: null,
      onUnload: null,
      onVolumeChange: null,
      onWaiting: null,
      onZoom: null,
      opacity: null,
      operator: null,
      order: null,
      orient: null,
      orientation: null,
      origin: null,
      overflow: null,
      overlay: null,
      overlinePosition: number,
      overlineThickness: number,
      paintOrder: null,
      panose1: null,
      path: null,
      pathLength: number,
      patternContentUnits: null,
      patternTransform: null,
      patternUnits: null,
      phase: null,
      ping: spaceSeparated,
      pitch: null,
      playbackOrder: null,
      pointerEvents: null,
      points: null,
      pointsAtX: number,
      pointsAtY: number,
      pointsAtZ: number,
      preserveAlpha: null,
      preserveAspectRatio: null,
      primitiveUnits: null,
      propagate: null,
      property: commaOrSpaceSeparated,
      r: null,
      radius: null,
      referrerPolicy: null,
      refX: null,
      refY: null,
      rel: commaOrSpaceSeparated,
      rev: commaOrSpaceSeparated,
      renderingIntent: null,
      repeatCount: null,
      repeatDur: null,
      requiredExtensions: commaOrSpaceSeparated,
      requiredFeatures: commaOrSpaceSeparated,
      requiredFonts: commaOrSpaceSeparated,
      requiredFormats: commaOrSpaceSeparated,
      resource: null,
      restart: null,
      result: null,
      rotate: null,
      rx: null,
      ry: null,
      scale: null,
      seed: null,
      shapeRendering: null,
      side: null,
      slope: null,
      snapshotTime: null,
      specularConstant: number,
      specularExponent: number,
      spreadMethod: null,
      spacing: null,
      startOffset: null,
      stdDeviation: null,
      stemh: null,
      stemv: null,
      stitchTiles: null,
      stopColor: null,
      stopOpacity: null,
      strikethroughPosition: number,
      strikethroughThickness: number,
      string: null,
      stroke: null,
      strokeDashArray: commaOrSpaceSeparated,
      strokeDashOffset: null,
      strokeLineCap: null,
      strokeLineJoin: null,
      strokeMiterLimit: number,
      strokeOpacity: number,
      strokeWidth: null,
      style: null,
      surfaceScale: number,
      syncBehavior: null,
      syncBehaviorDefault: null,
      syncMaster: null,
      syncTolerance: null,
      syncToleranceDefault: null,
      systemLanguage: commaOrSpaceSeparated,
      tabIndex: number,
      tableValues: null,
      target: null,
      targetX: number,
      targetY: number,
      textAnchor: null,
      textDecoration: null,
      textRendering: null,
      textLength: null,
      timelineBegin: null,
      title: null,
      transformBehavior: null,
      type: null,
      typeOf: commaOrSpaceSeparated,
      to: null,
      transform: null,
      transformOrigin: null,
      u1: null,
      u2: null,
      underlinePosition: number,
      underlineThickness: number,
      unicode: null,
      unicodeBidi: null,
      unicodeRange: null,
      unitsPerEm: number,
      values: null,
      vAlphabetic: number,
      vMathematical: number,
      vectorEffect: null,
      vHanging: number,
      vIdeographic: number,
      version: null,
      vertAdvY: number,
      vertOriginX: number,
      vertOriginY: number,
      viewBox: null,
      viewTarget: null,
      visibility: null,
      width: null,
      widths: null,
      wordSpacing: null,
      writingMode: null,
      x: null,
      x1: null,
      x2: null,
      xChannelSelector: null,
      xHeight: number,
      y: null,
      y1: null,
      y2: null,
      yChannelSelector: null,
      z: null,
      zoomAndPan: null
    },
    space: "svg",
    transform: caseSensitiveTransform
  });
  const xlink = create({
    properties: {
      xLinkActuate: null,
      xLinkArcRole: null,
      xLinkHref: null,
      xLinkRole: null,
      xLinkShow: null,
      xLinkTitle: null,
      xLinkType: null
    },
    space: "xlink",
    transform(_, property) {
      return "xlink:" + property.slice(5).toLowerCase();
    }
  });
  const xmlns = create({
    attributes: { xmlnsxlink: "xmlns:xlink" },
    properties: { xmlnsXLink: null, xmlns: null },
    space: "xmlns",
    transform: caseInsensitiveTransform
  });
  const xml = create({
    properties: { xmlBase: null, xmlLang: null, xmlSpace: null },
    space: "xml",
    transform(_, property) {
      return "xml:" + property.slice(3).toLowerCase();
    }
  });
  const hastToReact = {
    classId: "classID",
    dataType: "datatype",
    itemId: "itemID",
    strokeDashArray: "strokeDasharray",
    strokeDashOffset: "strokeDashoffset",
    strokeLineCap: "strokeLinecap",
    strokeLineJoin: "strokeLinejoin",
    strokeMiterLimit: "strokeMiterlimit",
    typeOf: "typeof",
    xLinkActuate: "xlinkActuate",
    xLinkArcRole: "xlinkArcrole",
    xLinkHref: "xlinkHref",
    xLinkRole: "xlinkRole",
    xLinkShow: "xlinkShow",
    xLinkTitle: "xlinkTitle",
    xLinkType: "xlinkType",
    xmlnsXLink: "xmlnsXlink"
  };
  const cap$1 = /[A-Z]/g;
  const dash = /-[a-z]/g;
  const valid = /^data[-\w.:]+$/i;
  function find(schema, value) {
    const normal = normalize$1(value);
    let property = value;
    let Type = Info;
    if (normal in schema.normal) {
      return schema.property[schema.normal[normal]];
    }
    if (normal.length > 4 && normal.slice(0, 4) === "data" && valid.test(value)) {
      if (value.charAt(4) === "-") {
        const rest = value.slice(5).replace(dash, camelcase);
        property = "data" + rest.charAt(0).toUpperCase() + rest.slice(1);
      } else {
        const rest = value.slice(4);
        if (!dash.test(rest)) {
          let dashes = rest.replace(cap$1, kebab);
          if (dashes.charAt(0) !== "-") {
            dashes = "-" + dashes;
          }
          value = "data" + dashes;
        }
      }
      Type = DefinedInfo;
    }
    return new Type(property, value);
  }
  function kebab($0) {
    return "-" + $0.toLowerCase();
  }
  function camelcase($0) {
    return $0.charAt(1).toUpperCase();
  }
  const html$2 = merge([aria, html$3, xlink, xmlns, xml], "html");
  const svg = merge([aria, svg$1, xlink, xmlns, xml], "svg");
  function stringify(values) {
    return values.join(" ").trim();
  }
  var cjs = {};
  var inlineStyleParser;
  var hasRequiredInlineStyleParser;
  function requireInlineStyleParser() {
    if (hasRequiredInlineStyleParser) return inlineStyleParser;
    hasRequiredInlineStyleParser = 1;
    var COMMENT_REGEX = /\/\*[^*]*\*+([^/*][^*]*\*+)*\//g;
    var NEWLINE_REGEX = /\n/g;
    var WHITESPACE_REGEX = /^\s*/;
    var PROPERTY_REGEX = /^(\*?[-#/*\\\w]+(\[[0-9a-z_-]+\])?)\s*/;
    var COLON_REGEX = /^:\s*/;
    var VALUE_REGEX = /^((?:'(?:\\'|.)*?'|"(?:\\"|.)*?"|\([^)]*?\)|[^};])+)/;
    var SEMICOLON_REGEX = /^[;\s]*/;
    var TRIM_REGEX = /^\s+|\s+$/g;
    var NEWLINE = "\n";
    var FORWARD_SLASH = "/";
    var ASTERISK = "*";
    var EMPTY_STRING = "";
    var TYPE_COMMENT = "comment";
    var TYPE_DECLARATION = "declaration";
    inlineStyleParser = function(style, options) {
      if (typeof style !== "string") {
        throw new TypeError("First argument must be a string");
      }
      if (!style) return [];
      options = options || {};
      var lineno = 1;
      var column = 1;
      function updatePosition(str) {
        var lines = str.match(NEWLINE_REGEX);
        if (lines) lineno += lines.length;
        var i = str.lastIndexOf(NEWLINE);
        column = ~i ? str.length - i : column + str.length;
      }
      function position2() {
        var start = { line: lineno, column };
        return function(node2) {
          node2.position = new Position(start);
          whitespace2();
          return node2;
        };
      }
      function Position(start) {
        this.start = start;
        this.end = { line: lineno, column };
        this.source = options.source;
      }
      Position.prototype.content = style;
      function error(msg) {
        var err = new Error(
          options.source + ":" + lineno + ":" + column + ": " + msg
        );
        err.reason = msg;
        err.filename = options.source;
        err.line = lineno;
        err.column = column;
        err.source = style;
        if (options.silent) ;
        else {
          throw err;
        }
      }
      function match(re2) {
        var m = re2.exec(style);
        if (!m) return;
        var str = m[0];
        updatePosition(str);
        style = style.slice(str.length);
        return m;
      }
      function whitespace2() {
        match(WHITESPACE_REGEX);
      }
      function comments(rules) {
        var c;
        rules = rules || [];
        while (c = comment()) {
          if (c !== false) {
            rules.push(c);
          }
        }
        return rules;
      }
      function comment() {
        var pos = position2();
        if (FORWARD_SLASH != style.charAt(0) || ASTERISK != style.charAt(1)) return;
        var i = 2;
        while (EMPTY_STRING != style.charAt(i) && (ASTERISK != style.charAt(i) || FORWARD_SLASH != style.charAt(i + 1))) {
          ++i;
        }
        i += 2;
        if (EMPTY_STRING === style.charAt(i - 1)) {
          return error("End of comment missing");
        }
        var str = style.slice(2, i - 2);
        column += 2;
        updatePosition(str);
        style = style.slice(i);
        column += 2;
        return pos({
          type: TYPE_COMMENT,
          comment: str
        });
      }
      function declaration() {
        var pos = position2();
        var prop = match(PROPERTY_REGEX);
        if (!prop) return;
        comment();
        if (!match(COLON_REGEX)) return error("property missing ':'");
        var val = match(VALUE_REGEX);
        var ret = pos({
          type: TYPE_DECLARATION,
          property: trim(prop[0].replace(COMMENT_REGEX, EMPTY_STRING)),
          value: val ? trim(val[0].replace(COMMENT_REGEX, EMPTY_STRING)) : EMPTY_STRING
        });
        match(SEMICOLON_REGEX);
        return ret;
      }
      function declarations() {
        var decls = [];
        comments(decls);
        var decl;
        while (decl = declaration()) {
          if (decl !== false) {
            decls.push(decl);
            comments(decls);
          }
        }
        return decls;
      }
      whitespace2();
      return declarations();
    };
    function trim(str) {
      return str ? str.replace(TRIM_REGEX, EMPTY_STRING) : EMPTY_STRING;
    }
    return inlineStyleParser;
  }
  var styleToObject;
  var hasRequiredStyleToObject;
  function requireStyleToObject() {
    if (hasRequiredStyleToObject) return styleToObject;
    hasRequiredStyleToObject = 1;
    var parse2 = requireInlineStyleParser();
    function StyleToObject(style, iterator) {
      var output = null;
      if (!style || typeof style !== "string") {
        return output;
      }
      var declaration;
      var declarations = parse2(style);
      var hasIterator = typeof iterator === "function";
      var property;
      var value;
      for (var i = 0, len = declarations.length; i < len; i++) {
        declaration = declarations[i];
        property = declaration.property;
        value = declaration.value;
        if (hasIterator) {
          iterator(property, value, declaration);
        } else if (value) {
          output || (output = {});
          output[property] = value;
        }
      }
      return output;
    }
    styleToObject = StyleToObject;
    return styleToObject;
  }
  var utilities = {};
  var hasRequiredUtilities;
  function requireUtilities() {
    if (hasRequiredUtilities) return utilities;
    hasRequiredUtilities = 1;
    utilities.__esModule = true;
    utilities.camelCase = void 0;
    var CUSTOM_PROPERTY_REGEX = /^--[a-zA-Z0-9-]+$/;
    var HYPHEN_REGEX = /-([a-z])/g;
    var NO_HYPHEN_REGEX = /^[^-]+$/;
    var VENDOR_PREFIX_REGEX = /^-(webkit|moz|ms|o)-/;
    var camelCase = function(property) {
      if (!property || NO_HYPHEN_REGEX.test(property) || CUSTOM_PROPERTY_REGEX.test(property)) {
        return property;
      }
      return property.toLowerCase().replace(VENDOR_PREFIX_REGEX, function(_, prefix) {
        return prefix + "-";
      }).replace(HYPHEN_REGEX, function(_, character) {
        return character.toUpperCase();
      });
    };
    utilities.camelCase = camelCase;
    return utilities;
  }
  var hasRequiredCjs;
  function requireCjs() {
    if (hasRequiredCjs) return cjs;
    hasRequiredCjs = 1;
    (function(exports2) {
      var __importDefault = cjs && cjs.__importDefault || function(mod) {
        return mod && mod.__esModule ? mod : { "default": mod };
      };
      exports2.__esModule = true;
      var style_to_object_1 = __importDefault(requireStyleToObject());
      var utilities_1 = requireUtilities();
      function StyleToJS(style) {
        if (!style || typeof style !== "string") {
          return {};
        }
        var output = {};
        style_to_object_1["default"](style, function(property, value) {
          if (property && value) {
            output[utilities_1.camelCase(property)] = value;
          }
        });
        return output;
      }
      exports2["default"] = StyleToJS;
    })(cjs);
    return cjs;
  }
  var cjsExports = requireCjs();
  const styleToJs = /* @__PURE__ */ getDefaultExportFromCjs(cjsExports);
  const pointEnd = point$2("end");
  const pointStart = point$2("start");
  function point$2(type) {
    return point2;
    function point2(node2) {
      const point3 = node2 && node2.position && node2.position[type] || {};
      if (typeof point3.line === "number" && point3.line > 0 && typeof point3.column === "number" && point3.column > 0) {
        return {
          line: point3.line,
          column: point3.column,
          offset: typeof point3.offset === "number" && point3.offset > -1 ? point3.offset : void 0
        };
      }
    }
  }
  function position$1(node2) {
    const start = pointStart(node2);
    const end = pointEnd(node2);
    if (start && end) {
      return { start, end };
    }
  }
  function stringifyPosition(value) {
    if (!value || typeof value !== "object") {
      return "";
    }
    if ("position" in value || "type" in value) {
      return position(value.position);
    }
    if ("start" in value || "end" in value) {
      return position(value);
    }
    if ("line" in value || "column" in value) {
      return point$1(value);
    }
    return "";
  }
  function point$1(point2) {
    return index(point2 && point2.line) + ":" + index(point2 && point2.column);
  }
  function position(pos) {
    return point$1(pos && pos.start) + "-" + point$1(pos && pos.end);
  }
  function index(value) {
    return value && typeof value === "number" ? value : 1;
  }
  class VFileMessage extends Error {
    /**
     * Create a message for `reason`.
     *
     * > 🪦 **Note**: also has obsolete signatures.
     *
     * @overload
     * @param {string} reason
     * @param {Options | null | undefined} [options]
     * @returns
     *
     * @overload
     * @param {string} reason
     * @param {Node | NodeLike | null | undefined} parent
     * @param {string | null | undefined} [origin]
     * @returns
     *
     * @overload
     * @param {string} reason
     * @param {Point | Position | null | undefined} place
     * @param {string | null | undefined} [origin]
     * @returns
     *
     * @overload
     * @param {string} reason
     * @param {string | null | undefined} [origin]
     * @returns
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {Node | NodeLike | null | undefined} parent
     * @param {string | null | undefined} [origin]
     * @returns
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {Point | Position | null | undefined} place
     * @param {string | null | undefined} [origin]
     * @returns
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {string | null | undefined} [origin]
     * @returns
     *
     * @param {Error | VFileMessage | string} causeOrReason
     *   Reason for message, should use markdown.
     * @param {Node | NodeLike | Options | Point | Position | string | null | undefined} [optionsOrParentOrPlace]
     *   Configuration (optional).
     * @param {string | null | undefined} [origin]
     *   Place in code where the message originates (example:
     *   `'my-package:my-rule'` or `'my-rule'`).
     * @returns
     *   Instance of `VFileMessage`.
     */
    // eslint-disable-next-line complexity
    constructor(causeOrReason, optionsOrParentOrPlace, origin) {
      super();
      if (typeof optionsOrParentOrPlace === "string") {
        origin = optionsOrParentOrPlace;
        optionsOrParentOrPlace = void 0;
      }
      let reason = "";
      let options = {};
      let legacyCause = false;
      if (optionsOrParentOrPlace) {
        if ("line" in optionsOrParentOrPlace && "column" in optionsOrParentOrPlace) {
          options = { place: optionsOrParentOrPlace };
        } else if ("start" in optionsOrParentOrPlace && "end" in optionsOrParentOrPlace) {
          options = { place: optionsOrParentOrPlace };
        } else if ("type" in optionsOrParentOrPlace) {
          options = {
            ancestors: [optionsOrParentOrPlace],
            place: optionsOrParentOrPlace.position
          };
        } else {
          options = { ...optionsOrParentOrPlace };
        }
      }
      if (typeof causeOrReason === "string") {
        reason = causeOrReason;
      } else if (!options.cause && causeOrReason) {
        legacyCause = true;
        reason = causeOrReason.message;
        options.cause = causeOrReason;
      }
      if (!options.ruleId && !options.source && typeof origin === "string") {
        const index2 = origin.indexOf(":");
        if (index2 === -1) {
          options.ruleId = origin;
        } else {
          options.source = origin.slice(0, index2);
          options.ruleId = origin.slice(index2 + 1);
        }
      }
      if (!options.place && options.ancestors && options.ancestors) {
        const parent = options.ancestors[options.ancestors.length - 1];
        if (parent) {
          options.place = parent.position;
        }
      }
      const start = options.place && "start" in options.place ? options.place.start : options.place;
      this.ancestors = options.ancestors || void 0;
      this.cause = options.cause || void 0;
      this.column = start ? start.column : void 0;
      this.fatal = void 0;
      this.file = "";
      this.message = reason;
      this.line = start ? start.line : void 0;
      this.name = stringifyPosition(options.place) || "1:1";
      this.place = options.place || void 0;
      this.reason = this.message;
      this.ruleId = options.ruleId || void 0;
      this.source = options.source || void 0;
      this.stack = legacyCause && options.cause && typeof options.cause.stack === "string" ? options.cause.stack : "";
      this.actual = void 0;
      this.expected = void 0;
      this.note = void 0;
      this.url = void 0;
    }
  }
  VFileMessage.prototype.file = "";
  VFileMessage.prototype.name = "";
  VFileMessage.prototype.reason = "";
  VFileMessage.prototype.message = "";
  VFileMessage.prototype.stack = "";
  VFileMessage.prototype.column = void 0;
  VFileMessage.prototype.line = void 0;
  VFileMessage.prototype.ancestors = void 0;
  VFileMessage.prototype.cause = void 0;
  VFileMessage.prototype.fatal = void 0;
  VFileMessage.prototype.place = void 0;
  VFileMessage.prototype.ruleId = void 0;
  VFileMessage.prototype.source = void 0;
  const own$3 = {}.hasOwnProperty;
  const emptyMap = /* @__PURE__ */ new Map();
  const cap = /[A-Z]/g;
  const tableElements = /* @__PURE__ */ new Set(["table", "tbody", "thead", "tfoot", "tr"]);
  const tableCellElement = /* @__PURE__ */ new Set(["td", "th"]);
  const docs = "https://github.com/syntax-tree/hast-util-to-jsx-runtime";
  function toJsxRuntime(tree, options) {
    if (!options || options.Fragment === void 0) {
      throw new TypeError("Expected `Fragment` in options");
    }
    const filePath = options.filePath || void 0;
    let create2;
    if (options.development) {
      if (typeof options.jsxDEV !== "function") {
        throw new TypeError(
          "Expected `jsxDEV` in options when `development: true`"
        );
      }
      create2 = developmentCreate(filePath, options.jsxDEV);
    } else {
      if (typeof options.jsx !== "function") {
        throw new TypeError("Expected `jsx` in production options");
      }
      if (typeof options.jsxs !== "function") {
        throw new TypeError("Expected `jsxs` in production options");
      }
      create2 = productionCreate(filePath, options.jsx, options.jsxs);
    }
    const state = {
      Fragment: options.Fragment,
      ancestors: [],
      components: options.components || {},
      create: create2,
      elementAttributeNameCase: options.elementAttributeNameCase || "react",
      evaluater: options.createEvaluater ? options.createEvaluater() : void 0,
      filePath,
      ignoreInvalidStyle: options.ignoreInvalidStyle || false,
      passKeys: options.passKeys !== false,
      passNode: options.passNode || false,
      schema: options.space === "svg" ? svg : html$2,
      stylePropertyNameCase: options.stylePropertyNameCase || "dom",
      tableCellAlignToStyle: options.tableCellAlignToStyle !== false
    };
    const result = one$1(state, tree, void 0);
    if (result && typeof result !== "string") {
      return result;
    }
    return state.create(
      tree,
      state.Fragment,
      { children: result || void 0 },
      void 0
    );
  }
  function one$1(state, node2, key) {
    if (node2.type === "element") {
      return element$1(state, node2, key);
    }
    if (node2.type === "mdxFlowExpression" || node2.type === "mdxTextExpression") {
      return mdxExpression(state, node2);
    }
    if (node2.type === "mdxJsxFlowElement" || node2.type === "mdxJsxTextElement") {
      return mdxJsxElement(state, node2, key);
    }
    if (node2.type === "mdxjsEsm") {
      return mdxEsm(state, node2);
    }
    if (node2.type === "root") {
      return root$2(state, node2, key);
    }
    if (node2.type === "text") {
      return text$5(state, node2);
    }
  }
  function element$1(state, node2, key) {
    const parentSchema = state.schema;
    let schema = parentSchema;
    if (node2.tagName.toLowerCase() === "svg" && parentSchema.space === "html") {
      schema = svg;
      state.schema = schema;
    }
    state.ancestors.push(node2);
    const type = findComponentFromName(state, node2.tagName, false);
    const props = createElementProps(state, node2);
    let children = createChildren(state, node2);
    if (tableElements.has(node2.tagName)) {
      children = children.filter(function(child) {
        return typeof child === "string" ? !whitespace(child) : true;
      });
    }
    addNode(state, props, type, node2);
    addChildren(props, children);
    state.ancestors.pop();
    state.schema = parentSchema;
    return state.create(node2, type, props, key);
  }
  function mdxExpression(state, node2) {
    if (node2.data && node2.data.estree && state.evaluater) {
      const program = node2.data.estree;
      const expression = program.body[0];
      ok$1(expression.type === "ExpressionStatement");
      return (
        /** @type {Child | undefined} */
        state.evaluater.evaluateExpression(expression.expression)
      );
    }
    crashEstree(state, node2.position);
  }
  function mdxEsm(state, node2) {
    if (node2.data && node2.data.estree && state.evaluater) {
      return (
        /** @type {Child | undefined} */
        state.evaluater.evaluateProgram(node2.data.estree)
      );
    }
    crashEstree(state, node2.position);
  }
  function mdxJsxElement(state, node2, key) {
    const parentSchema = state.schema;
    let schema = parentSchema;
    if (node2.name === "svg" && parentSchema.space === "html") {
      schema = svg;
      state.schema = schema;
    }
    state.ancestors.push(node2);
    const type = node2.name === null ? state.Fragment : findComponentFromName(state, node2.name, true);
    const props = createJsxElementProps(state, node2);
    const children = createChildren(state, node2);
    addNode(state, props, type, node2);
    addChildren(props, children);
    state.ancestors.pop();
    state.schema = parentSchema;
    return state.create(node2, type, props, key);
  }
  function root$2(state, node2, key) {
    const props = {};
    addChildren(props, createChildren(state, node2));
    return state.create(node2, state.Fragment, props, key);
  }
  function text$5(_, node2) {
    return node2.value;
  }
  function addNode(state, props, type, node2) {
    if (typeof type !== "string" && type !== state.Fragment && state.passNode) {
      props.node = node2;
    }
  }
  function addChildren(props, children) {
    if (children.length > 0) {
      const value = children.length > 1 ? children : children[0];
      if (value) {
        props.children = value;
      }
    }
  }
  function productionCreate(_, jsx, jsxs) {
    return create2;
    function create2(_2, type, props, key) {
      const isStaticChildren = Array.isArray(props.children);
      const fn = isStaticChildren ? jsxs : jsx;
      return key ? fn(type, props, key) : fn(type, props);
    }
  }
  function developmentCreate(filePath, jsxDEV) {
    return create2;
    function create2(node2, type, props, key) {
      const isStaticChildren = Array.isArray(props.children);
      const point2 = pointStart(node2);
      return jsxDEV(
        type,
        props,
        key,
        isStaticChildren,
        {
          columnNumber: point2 ? point2.column - 1 : void 0,
          fileName: filePath,
          lineNumber: point2 ? point2.line : void 0
        },
        void 0
      );
    }
  }
  function createElementProps(state, node2) {
    const props = {};
    let alignValue;
    let prop;
    for (prop in node2.properties) {
      if (prop !== "children" && own$3.call(node2.properties, prop)) {
        const result = createProperty(state, prop, node2.properties[prop]);
        if (result) {
          const [key, value] = result;
          if (state.tableCellAlignToStyle && key === "align" && typeof value === "string" && tableCellElement.has(node2.tagName)) {
            alignValue = value;
          } else {
            props[key] = value;
          }
        }
      }
    }
    if (alignValue) {
      const style = (
        /** @type {Style} */
        props.style || (props.style = {})
      );
      style[state.stylePropertyNameCase === "css" ? "text-align" : "textAlign"] = alignValue;
    }
    return props;
  }
  function createJsxElementProps(state, node2) {
    const props = {};
    for (const attribute of node2.attributes) {
      if (attribute.type === "mdxJsxExpressionAttribute") {
        if (attribute.data && attribute.data.estree && state.evaluater) {
          const program = attribute.data.estree;
          const expression = program.body[0];
          ok$1(expression.type === "ExpressionStatement");
          const objectExpression = expression.expression;
          ok$1(objectExpression.type === "ObjectExpression");
          const property = objectExpression.properties[0];
          ok$1(property.type === "SpreadElement");
          Object.assign(
            props,
            state.evaluater.evaluateExpression(property.argument)
          );
        } else {
          crashEstree(state, node2.position);
        }
      } else {
        const name2 = attribute.name;
        let value;
        if (attribute.value && typeof attribute.value === "object") {
          if (attribute.value.data && attribute.value.data.estree && state.evaluater) {
            const program = attribute.value.data.estree;
            const expression = program.body[0];
            ok$1(expression.type === "ExpressionStatement");
            value = state.evaluater.evaluateExpression(expression.expression);
          } else {
            crashEstree(state, node2.position);
          }
        } else {
          value = attribute.value === null ? true : attribute.value;
        }
        props[name2] = /** @type {Props[keyof Props]} */
        value;
      }
    }
    return props;
  }
  function createChildren(state, node2) {
    const children = [];
    let index2 = -1;
    const countsByName = state.passKeys ? /* @__PURE__ */ new Map() : emptyMap;
    while (++index2 < node2.children.length) {
      const child = node2.children[index2];
      let key;
      if (state.passKeys) {
        const name2 = child.type === "element" ? child.tagName : child.type === "mdxJsxFlowElement" || child.type === "mdxJsxTextElement" ? child.name : void 0;
        if (name2) {
          const count = countsByName.get(name2) || 0;
          key = name2 + "-" + count;
          countsByName.set(name2, count + 1);
        }
      }
      const result = one$1(state, child, key);
      if (result !== void 0) children.push(result);
    }
    return children;
  }
  function createProperty(state, prop, value) {
    const info = find(state.schema, prop);
    if (value === null || value === void 0 || typeof value === "number" && Number.isNaN(value)) {
      return;
    }
    if (Array.isArray(value)) {
      value = info.commaSeparated ? stringify$1(value) : stringify(value);
    }
    if (info.property === "style") {
      let styleObject = typeof value === "object" ? value : parseStyle(state, String(value));
      if (state.stylePropertyNameCase === "css") {
        styleObject = transformStylesToCssCasing(styleObject);
      }
      return ["style", styleObject];
    }
    return [
      state.elementAttributeNameCase === "react" && info.space ? hastToReact[info.property] || info.property : info.attribute,
      value
    ];
  }
  function parseStyle(state, value) {
    try {
      return styleToJs(value, { reactCompat: true });
    } catch (error) {
      if (state.ignoreInvalidStyle) {
        return {};
      }
      const cause = (
        /** @type {Error} */
        error
      );
      const message = new VFileMessage("Cannot parse `style` attribute", {
        ancestors: state.ancestors,
        cause,
        ruleId: "style",
        source: "hast-util-to-jsx-runtime"
      });
      message.file = state.filePath || void 0;
      message.url = docs + "#cannot-parse-style-attribute";
      throw message;
    }
  }
  function findComponentFromName(state, name$1, allowExpression) {
    let result;
    if (!allowExpression) {
      result = { type: "Literal", value: name$1 };
    } else if (name$1.includes(".")) {
      const identifiers = name$1.split(".");
      let index2 = -1;
      let node2;
      while (++index2 < identifiers.length) {
        const prop = name(identifiers[index2]) ? { type: "Identifier", name: identifiers[index2] } : { type: "Literal", value: identifiers[index2] };
        node2 = node2 ? {
          type: "MemberExpression",
          object: node2,
          property: prop,
          computed: Boolean(index2 && prop.type === "Literal"),
          optional: false
        } : prop;
      }
      result = node2;
    } else {
      result = name(name$1) && !/^[a-z]/.test(name$1) ? { type: "Identifier", name: name$1 } : { type: "Literal", value: name$1 };
    }
    if (result.type === "Literal") {
      const name2 = (
        /** @type {string | number} */
        result.value
      );
      return own$3.call(state.components, name2) ? state.components[name2] : name2;
    }
    if (state.evaluater) {
      return state.evaluater.evaluateExpression(result);
    }
    crashEstree(state);
  }
  function crashEstree(state, place) {
    const message = new VFileMessage(
      "Cannot handle MDX estrees without `createEvaluater`",
      {
        ancestors: state.ancestors,
        place,
        ruleId: "mdx-estree",
        source: "hast-util-to-jsx-runtime"
      }
    );
    message.file = state.filePath || void 0;
    message.url = docs + "#cannot-handle-mdx-estrees-without-createevaluater";
    throw message;
  }
  function transformStylesToCssCasing(domCasing) {
    const cssCasing = {};
    let from;
    for (from in domCasing) {
      if (own$3.call(domCasing, from)) {
        cssCasing[transformStyleToCssCasing(from)] = domCasing[from];
      }
    }
    return cssCasing;
  }
  function transformStyleToCssCasing(from) {
    let to = from.replace(cap, toDash);
    if (to.slice(0, 3) === "ms-") to = "-" + to;
    return to;
  }
  function toDash($0) {
    return "-" + $0.toLowerCase();
  }
  const urlAttributes = {
    action: ["form"],
    cite: ["blockquote", "del", "ins", "q"],
    data: ["object"],
    formAction: ["button", "input"],
    href: ["a", "area", "base", "link"],
    icon: ["menuitem"],
    itemId: null,
    manifest: ["html"],
    ping: ["a", "area"],
    poster: ["video"],
    src: [
      "audio",
      "embed",
      "iframe",
      "img",
      "input",
      "script",
      "source",
      "track",
      "video"
    ]
  };
  const emptyOptions$2 = {};
  function toString$1(value, options) {
    const settings = emptyOptions$2;
    const includeImageAlt = typeof settings.includeImageAlt === "boolean" ? settings.includeImageAlt : true;
    const includeHtml = typeof settings.includeHtml === "boolean" ? settings.includeHtml : true;
    return one(value, includeImageAlt, includeHtml);
  }
  function one(value, includeImageAlt, includeHtml) {
    if (node(value)) {
      if ("value" in value) {
        return value.type === "html" && !includeHtml ? "" : value.value;
      }
      if (includeImageAlt && "alt" in value && value.alt) {
        return value.alt;
      }
      if ("children" in value) {
        return all(value.children, includeImageAlt, includeHtml);
      }
    }
    if (Array.isArray(value)) {
      return all(value, includeImageAlt, includeHtml);
    }
    return "";
  }
  function all(values, includeImageAlt, includeHtml) {
    const result = [];
    let index2 = -1;
    while (++index2 < values.length) {
      result[index2] = one(values[index2], includeImageAlt, includeHtml);
    }
    return result.join("");
  }
  function node(value) {
    return Boolean(value && typeof value === "object");
  }
  const element = document.createElement("i");
  function decodeNamedCharacterReference(value) {
    const characterReference2 = "&" + value + ";";
    element.innerHTML = characterReference2;
    const character = element.textContent;
    if (character.charCodeAt(character.length - 1) === 59 && value !== "semi") {
      return false;
    }
    return character === characterReference2 ? false : character;
  }
  function splice(list2, start, remove, items) {
    const end = list2.length;
    let chunkStart = 0;
    let parameters;
    if (start < 0) {
      start = -start > end ? 0 : end + start;
    } else {
      start = start > end ? end : start;
    }
    remove = remove > 0 ? remove : 0;
    if (items.length < 1e4) {
      parameters = Array.from(items);
      parameters.unshift(start, remove);
      list2.splice(...parameters);
    } else {
      if (remove) list2.splice(start, remove);
      while (chunkStart < items.length) {
        parameters = items.slice(chunkStart, chunkStart + 1e4);
        parameters.unshift(start, 0);
        list2.splice(...parameters);
        chunkStart += 1e4;
        start += 1e4;
      }
    }
  }
  function push(list2, items) {
    if (list2.length > 0) {
      splice(list2, list2.length, 0, items);
      return list2;
    }
    return items;
  }
  const hasOwnProperty = {}.hasOwnProperty;
  function combineExtensions(extensions) {
    const all2 = {};
    let index2 = -1;
    while (++index2 < extensions.length) {
      syntaxExtension(all2, extensions[index2]);
    }
    return all2;
  }
  function syntaxExtension(all2, extension2) {
    let hook;
    for (hook in extension2) {
      const maybe = hasOwnProperty.call(all2, hook) ? all2[hook] : void 0;
      const left = maybe || (all2[hook] = {});
      const right = extension2[hook];
      let code2;
      if (right) {
        for (code2 in right) {
          if (!hasOwnProperty.call(left, code2)) left[code2] = [];
          const value = right[code2];
          constructs(
            // @ts-expect-error Looks like a list.
            left[code2],
            Array.isArray(value) ? value : value ? [value] : []
          );
        }
      }
    }
  }
  function constructs(existing, list2) {
    let index2 = -1;
    const before = [];
    while (++index2 < list2.length) {
      (list2[index2].add === "after" ? existing : before).push(list2[index2]);
    }
    splice(existing, 0, 0, before);
  }
  function decodeNumericCharacterReference(value, base) {
    const code2 = Number.parseInt(value, base);
    if (
      // C0 except for HT, LF, FF, CR, space.
      code2 < 9 || code2 === 11 || code2 > 13 && code2 < 32 || // Control character (DEL) of C0, and C1 controls.
      code2 > 126 && code2 < 160 || // Lone high surrogates and low surrogates.
      code2 > 55295 && code2 < 57344 || // Noncharacters.
      code2 > 64975 && code2 < 65008 || (code2 & 65535) === 65535 || (code2 & 65535) === 65534 || // Out of range
      code2 > 1114111
    ) {
      return "�";
    }
    return String.fromCharCode(code2);
  }
  function normalizeIdentifier(value) {
    return value.replace(/[\t\n\r ]+/g, " ").replace(/^ | $/g, "").toLowerCase().toUpperCase();
  }
  const asciiAlpha = regexCheck(/[A-Za-z]/);
  const asciiAlphanumeric = regexCheck(/[\dA-Za-z]/);
  const asciiAtext = regexCheck(/[#-'*+\--9=?A-Z^-~]/);
  function asciiControl(code2) {
    return (
      // Special whitespace codes (which have negative values), C0 and Control
      // character DEL
      code2 !== null && (code2 < 32 || code2 === 127)
    );
  }
  const asciiDigit = regexCheck(/\d/);
  const asciiHexDigit = regexCheck(/[\dA-Fa-f]/);
  const asciiPunctuation = regexCheck(/[!-/:-@[-`{-~]/);
  function markdownLineEnding(code2) {
    return code2 !== null && code2 < -2;
  }
  function markdownLineEndingOrSpace(code2) {
    return code2 !== null && (code2 < 0 || code2 === 32);
  }
  function markdownSpace(code2) {
    return code2 === -2 || code2 === -1 || code2 === 32;
  }
  const unicodePunctuation = regexCheck(new RegExp("\\p{P}", "u"));
  const unicodeWhitespace = regexCheck(/\s/);
  function regexCheck(regex) {
    return check;
    function check(code2) {
      return code2 !== null && code2 > -1 && regex.test(String.fromCharCode(code2));
    }
  }
  function normalizeUri(value) {
    const result = [];
    let index2 = -1;
    let start = 0;
    let skip = 0;
    while (++index2 < value.length) {
      const code2 = value.charCodeAt(index2);
      let replace2 = "";
      if (code2 === 37 && asciiAlphanumeric(value.charCodeAt(index2 + 1)) && asciiAlphanumeric(value.charCodeAt(index2 + 2))) {
        skip = 2;
      } else if (code2 < 128) {
        if (!/[!#$&-;=?-Z_a-z~]/.test(String.fromCharCode(code2))) {
          replace2 = String.fromCharCode(code2);
        }
      } else if (code2 > 55295 && code2 < 57344) {
        const next = value.charCodeAt(index2 + 1);
        if (code2 < 56320 && next > 56319 && next < 57344) {
          replace2 = String.fromCharCode(code2, next);
          skip = 1;
        } else {
          replace2 = "�";
        }
      } else {
        replace2 = String.fromCharCode(code2);
      }
      if (replace2) {
        result.push(value.slice(start, index2), encodeURIComponent(replace2));
        start = index2 + skip + 1;
        replace2 = "";
      }
      if (skip) {
        index2 += skip;
        skip = 0;
      }
    }
    return result.join("") + value.slice(start);
  }
  function factorySpace(effects, ok2, type, max) {
    const limit = max ? max - 1 : Number.POSITIVE_INFINITY;
    let size = 0;
    return start;
    function start(code2) {
      if (markdownSpace(code2)) {
        effects.enter(type);
        return prefix(code2);
      }
      return ok2(code2);
    }
    function prefix(code2) {
      if (markdownSpace(code2) && size++ < limit) {
        effects.consume(code2);
        return prefix;
      }
      effects.exit(type);
      return ok2(code2);
    }
  }
  const content$1 = {
    tokenize: initializeContent
  };
  function initializeContent(effects) {
    const contentStart = effects.attempt(
      this.parser.constructs.contentInitial,
      afterContentStartConstruct,
      paragraphInitial
    );
    let previous2;
    return contentStart;
    function afterContentStartConstruct(code2) {
      if (code2 === null) {
        effects.consume(code2);
        return;
      }
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      return factorySpace(effects, contentStart, "linePrefix");
    }
    function paragraphInitial(code2) {
      effects.enter("paragraph");
      return lineStart(code2);
    }
    function lineStart(code2) {
      const token = effects.enter("chunkText", {
        contentType: "text",
        previous: previous2
      });
      if (previous2) {
        previous2.next = token;
      }
      previous2 = token;
      return data(code2);
    }
    function data(code2) {
      if (code2 === null) {
        effects.exit("chunkText");
        effects.exit("paragraph");
        effects.consume(code2);
        return;
      }
      if (markdownLineEnding(code2)) {
        effects.consume(code2);
        effects.exit("chunkText");
        return lineStart;
      }
      effects.consume(code2);
      return data;
    }
  }
  const document$2 = {
    tokenize: initializeDocument
  };
  const containerConstruct = {
    tokenize: tokenizeContainer
  };
  function initializeDocument(effects) {
    const self2 = this;
    const stack = [];
    let continued = 0;
    let childFlow;
    let childToken;
    let lineStartOffset;
    return start;
    function start(code2) {
      if (continued < stack.length) {
        const item = stack[continued];
        self2.containerState = item[1];
        return effects.attempt(
          item[0].continuation,
          documentContinue,
          checkNewContainers
        )(code2);
      }
      return checkNewContainers(code2);
    }
    function documentContinue(code2) {
      continued++;
      if (self2.containerState._closeFlow) {
        self2.containerState._closeFlow = void 0;
        if (childFlow) {
          closeFlow();
        }
        const indexBeforeExits = self2.events.length;
        let indexBeforeFlow = indexBeforeExits;
        let point2;
        while (indexBeforeFlow--) {
          if (self2.events[indexBeforeFlow][0] === "exit" && self2.events[indexBeforeFlow][1].type === "chunkFlow") {
            point2 = self2.events[indexBeforeFlow][1].end;
            break;
          }
        }
        exitContainers(continued);
        let index2 = indexBeforeExits;
        while (index2 < self2.events.length) {
          self2.events[index2][1].end = Object.assign({}, point2);
          index2++;
        }
        splice(
          self2.events,
          indexBeforeFlow + 1,
          0,
          self2.events.slice(indexBeforeExits)
        );
        self2.events.length = index2;
        return checkNewContainers(code2);
      }
      return start(code2);
    }
    function checkNewContainers(code2) {
      if (continued === stack.length) {
        if (!childFlow) {
          return documentContinued(code2);
        }
        if (childFlow.currentConstruct && childFlow.currentConstruct.concrete) {
          return flowStart(code2);
        }
        self2.interrupt = Boolean(
          childFlow.currentConstruct && !childFlow._gfmTableDynamicInterruptHack
        );
      }
      self2.containerState = {};
      return effects.check(
        containerConstruct,
        thereIsANewContainer,
        thereIsNoNewContainer
      )(code2);
    }
    function thereIsANewContainer(code2) {
      if (childFlow) closeFlow();
      exitContainers(continued);
      return documentContinued(code2);
    }
    function thereIsNoNewContainer(code2) {
      self2.parser.lazy[self2.now().line] = continued !== stack.length;
      lineStartOffset = self2.now().offset;
      return flowStart(code2);
    }
    function documentContinued(code2) {
      self2.containerState = {};
      return effects.attempt(
        containerConstruct,
        containerContinue,
        flowStart
      )(code2);
    }
    function containerContinue(code2) {
      continued++;
      stack.push([self2.currentConstruct, self2.containerState]);
      return documentContinued(code2);
    }
    function flowStart(code2) {
      if (code2 === null) {
        if (childFlow) closeFlow();
        exitContainers(0);
        effects.consume(code2);
        return;
      }
      childFlow = childFlow || self2.parser.flow(self2.now());
      effects.enter("chunkFlow", {
        contentType: "flow",
        previous: childToken,
        _tokenizer: childFlow
      });
      return flowContinue(code2);
    }
    function flowContinue(code2) {
      if (code2 === null) {
        writeToChild(effects.exit("chunkFlow"), true);
        exitContainers(0);
        effects.consume(code2);
        return;
      }
      if (markdownLineEnding(code2)) {
        effects.consume(code2);
        writeToChild(effects.exit("chunkFlow"));
        continued = 0;
        self2.interrupt = void 0;
        return start;
      }
      effects.consume(code2);
      return flowContinue;
    }
    function writeToChild(token, eof) {
      const stream = self2.sliceStream(token);
      if (eof) stream.push(null);
      token.previous = childToken;
      if (childToken) childToken.next = token;
      childToken = token;
      childFlow.defineSkip(token.start);
      childFlow.write(stream);
      if (self2.parser.lazy[token.start.line]) {
        let index2 = childFlow.events.length;
        while (index2--) {
          if (
            // The token starts before the line ending…
            childFlow.events[index2][1].start.offset < lineStartOffset && // …and either is not ended yet…
            (!childFlow.events[index2][1].end || // …or ends after it.
            childFlow.events[index2][1].end.offset > lineStartOffset)
          ) {
            return;
          }
        }
        const indexBeforeExits = self2.events.length;
        let indexBeforeFlow = indexBeforeExits;
        let seen;
        let point2;
        while (indexBeforeFlow--) {
          if (self2.events[indexBeforeFlow][0] === "exit" && self2.events[indexBeforeFlow][1].type === "chunkFlow") {
            if (seen) {
              point2 = self2.events[indexBeforeFlow][1].end;
              break;
            }
            seen = true;
          }
        }
        exitContainers(continued);
        index2 = indexBeforeExits;
        while (index2 < self2.events.length) {
          self2.events[index2][1].end = Object.assign({}, point2);
          index2++;
        }
        splice(
          self2.events,
          indexBeforeFlow + 1,
          0,
          self2.events.slice(indexBeforeExits)
        );
        self2.events.length = index2;
      }
    }
    function exitContainers(size) {
      let index2 = stack.length;
      while (index2-- > size) {
        const entry = stack[index2];
        self2.containerState = entry[1];
        entry[0].exit.call(self2, effects);
      }
      stack.length = size;
    }
    function closeFlow() {
      childFlow.write([null]);
      childToken = void 0;
      childFlow = void 0;
      self2.containerState._closeFlow = void 0;
    }
  }
  function tokenizeContainer(effects, ok2, nok) {
    return factorySpace(
      effects,
      effects.attempt(this.parser.constructs.document, ok2, nok),
      "linePrefix",
      this.parser.constructs.disable.null.includes("codeIndented") ? void 0 : 4
    );
  }
  function classifyCharacter(code2) {
    if (code2 === null || markdownLineEndingOrSpace(code2) || unicodeWhitespace(code2)) {
      return 1;
    }
    if (unicodePunctuation(code2)) {
      return 2;
    }
  }
  function resolveAll(constructs2, events, context) {
    const called = [];
    let index2 = -1;
    while (++index2 < constructs2.length) {
      const resolve = constructs2[index2].resolveAll;
      if (resolve && !called.includes(resolve)) {
        events = resolve(events, context);
        called.push(resolve);
      }
    }
    return events;
  }
  const attention = {
    name: "attention",
    tokenize: tokenizeAttention,
    resolveAll: resolveAllAttention
  };
  function resolveAllAttention(events, context) {
    let index2 = -1;
    let open;
    let group;
    let text2;
    let openingSequence;
    let closingSequence;
    let use;
    let nextEvents;
    let offset;
    while (++index2 < events.length) {
      if (events[index2][0] === "enter" && events[index2][1].type === "attentionSequence" && events[index2][1]._close) {
        open = index2;
        while (open--) {
          if (events[open][0] === "exit" && events[open][1].type === "attentionSequence" && events[open][1]._open && // If the markers are the same:
          context.sliceSerialize(events[open][1]).charCodeAt(0) === context.sliceSerialize(events[index2][1]).charCodeAt(0)) {
            if ((events[open][1]._close || events[index2][1]._open) && (events[index2][1].end.offset - events[index2][1].start.offset) % 3 && !((events[open][1].end.offset - events[open][1].start.offset + events[index2][1].end.offset - events[index2][1].start.offset) % 3)) {
              continue;
            }
            use = events[open][1].end.offset - events[open][1].start.offset > 1 && events[index2][1].end.offset - events[index2][1].start.offset > 1 ? 2 : 1;
            const start = Object.assign({}, events[open][1].end);
            const end = Object.assign({}, events[index2][1].start);
            movePoint(start, -use);
            movePoint(end, use);
            openingSequence = {
              type: use > 1 ? "strongSequence" : "emphasisSequence",
              start,
              end: Object.assign({}, events[open][1].end)
            };
            closingSequence = {
              type: use > 1 ? "strongSequence" : "emphasisSequence",
              start: Object.assign({}, events[index2][1].start),
              end
            };
            text2 = {
              type: use > 1 ? "strongText" : "emphasisText",
              start: Object.assign({}, events[open][1].end),
              end: Object.assign({}, events[index2][1].start)
            };
            group = {
              type: use > 1 ? "strong" : "emphasis",
              start: Object.assign({}, openingSequence.start),
              end: Object.assign({}, closingSequence.end)
            };
            events[open][1].end = Object.assign({}, openingSequence.start);
            events[index2][1].start = Object.assign({}, closingSequence.end);
            nextEvents = [];
            if (events[open][1].end.offset - events[open][1].start.offset) {
              nextEvents = push(nextEvents, [
                ["enter", events[open][1], context],
                ["exit", events[open][1], context]
              ]);
            }
            nextEvents = push(nextEvents, [
              ["enter", group, context],
              ["enter", openingSequence, context],
              ["exit", openingSequence, context],
              ["enter", text2, context]
            ]);
            nextEvents = push(
              nextEvents,
              resolveAll(
                context.parser.constructs.insideSpan.null,
                events.slice(open + 1, index2),
                context
              )
            );
            nextEvents = push(nextEvents, [
              ["exit", text2, context],
              ["enter", closingSequence, context],
              ["exit", closingSequence, context],
              ["exit", group, context]
            ]);
            if (events[index2][1].end.offset - events[index2][1].start.offset) {
              offset = 2;
              nextEvents = push(nextEvents, [
                ["enter", events[index2][1], context],
                ["exit", events[index2][1], context]
              ]);
            } else {
              offset = 0;
            }
            splice(events, open - 1, index2 - open + 3, nextEvents);
            index2 = open + nextEvents.length - offset - 2;
            break;
          }
        }
      }
    }
    index2 = -1;
    while (++index2 < events.length) {
      if (events[index2][1].type === "attentionSequence") {
        events[index2][1].type = "data";
      }
    }
    return events;
  }
  function tokenizeAttention(effects, ok2) {
    const attentionMarkers2 = this.parser.constructs.attentionMarkers.null;
    const previous2 = this.previous;
    const before = classifyCharacter(previous2);
    let marker;
    return start;
    function start(code2) {
      marker = code2;
      effects.enter("attentionSequence");
      return inside(code2);
    }
    function inside(code2) {
      if (code2 === marker) {
        effects.consume(code2);
        return inside;
      }
      const token = effects.exit("attentionSequence");
      const after = classifyCharacter(code2);
      const open = !after || after === 2 && before || attentionMarkers2.includes(code2);
      const close = !before || before === 2 && after || attentionMarkers2.includes(previous2);
      token._open = Boolean(marker === 42 ? open : open && (before || !close));
      token._close = Boolean(marker === 42 ? close : close && (after || !open));
      return ok2(code2);
    }
  }
  function movePoint(point2, offset) {
    point2.column += offset;
    point2.offset += offset;
    point2._bufferIndex += offset;
  }
  const autolink = {
    name: "autolink",
    tokenize: tokenizeAutolink
  };
  function tokenizeAutolink(effects, ok2, nok) {
    let size = 0;
    return start;
    function start(code2) {
      effects.enter("autolink");
      effects.enter("autolinkMarker");
      effects.consume(code2);
      effects.exit("autolinkMarker");
      effects.enter("autolinkProtocol");
      return open;
    }
    function open(code2) {
      if (asciiAlpha(code2)) {
        effects.consume(code2);
        return schemeOrEmailAtext;
      }
      return emailAtext(code2);
    }
    function schemeOrEmailAtext(code2) {
      if (code2 === 43 || code2 === 45 || code2 === 46 || asciiAlphanumeric(code2)) {
        size = 1;
        return schemeInsideOrEmailAtext(code2);
      }
      return emailAtext(code2);
    }
    function schemeInsideOrEmailAtext(code2) {
      if (code2 === 58) {
        effects.consume(code2);
        size = 0;
        return urlInside;
      }
      if ((code2 === 43 || code2 === 45 || code2 === 46 || asciiAlphanumeric(code2)) && size++ < 32) {
        effects.consume(code2);
        return schemeInsideOrEmailAtext;
      }
      size = 0;
      return emailAtext(code2);
    }
    function urlInside(code2) {
      if (code2 === 62) {
        effects.exit("autolinkProtocol");
        effects.enter("autolinkMarker");
        effects.consume(code2);
        effects.exit("autolinkMarker");
        effects.exit("autolink");
        return ok2;
      }
      if (code2 === null || code2 === 32 || code2 === 60 || asciiControl(code2)) {
        return nok(code2);
      }
      effects.consume(code2);
      return urlInside;
    }
    function emailAtext(code2) {
      if (code2 === 64) {
        effects.consume(code2);
        return emailAtSignOrDot;
      }
      if (asciiAtext(code2)) {
        effects.consume(code2);
        return emailAtext;
      }
      return nok(code2);
    }
    function emailAtSignOrDot(code2) {
      return asciiAlphanumeric(code2) ? emailLabel(code2) : nok(code2);
    }
    function emailLabel(code2) {
      if (code2 === 46) {
        effects.consume(code2);
        size = 0;
        return emailAtSignOrDot;
      }
      if (code2 === 62) {
        effects.exit("autolinkProtocol").type = "autolinkEmail";
        effects.enter("autolinkMarker");
        effects.consume(code2);
        effects.exit("autolinkMarker");
        effects.exit("autolink");
        return ok2;
      }
      return emailValue(code2);
    }
    function emailValue(code2) {
      if ((code2 === 45 || asciiAlphanumeric(code2)) && size++ < 63) {
        const next = code2 === 45 ? emailValue : emailLabel;
        effects.consume(code2);
        return next;
      }
      return nok(code2);
    }
  }
  const blankLine = {
    tokenize: tokenizeBlankLine,
    partial: true
  };
  function tokenizeBlankLine(effects, ok2, nok) {
    return start;
    function start(code2) {
      return markdownSpace(code2) ? factorySpace(effects, after, "linePrefix")(code2) : after(code2);
    }
    function after(code2) {
      return code2 === null || markdownLineEnding(code2) ? ok2(code2) : nok(code2);
    }
  }
  const blockQuote = {
    name: "blockQuote",
    tokenize: tokenizeBlockQuoteStart,
    continuation: {
      tokenize: tokenizeBlockQuoteContinuation
    },
    exit: exit$1
  };
  function tokenizeBlockQuoteStart(effects, ok2, nok) {
    const self2 = this;
    return start;
    function start(code2) {
      if (code2 === 62) {
        const state = self2.containerState;
        if (!state.open) {
          effects.enter("blockQuote", {
            _container: true
          });
          state.open = true;
        }
        effects.enter("blockQuotePrefix");
        effects.enter("blockQuoteMarker");
        effects.consume(code2);
        effects.exit("blockQuoteMarker");
        return after;
      }
      return nok(code2);
    }
    function after(code2) {
      if (markdownSpace(code2)) {
        effects.enter("blockQuotePrefixWhitespace");
        effects.consume(code2);
        effects.exit("blockQuotePrefixWhitespace");
        effects.exit("blockQuotePrefix");
        return ok2;
      }
      effects.exit("blockQuotePrefix");
      return ok2(code2);
    }
  }
  function tokenizeBlockQuoteContinuation(effects, ok2, nok) {
    const self2 = this;
    return contStart;
    function contStart(code2) {
      if (markdownSpace(code2)) {
        return factorySpace(
          effects,
          contBefore,
          "linePrefix",
          self2.parser.constructs.disable.null.includes("codeIndented") ? void 0 : 4
        )(code2);
      }
      return contBefore(code2);
    }
    function contBefore(code2) {
      return effects.attempt(blockQuote, ok2, nok)(code2);
    }
  }
  function exit$1(effects) {
    effects.exit("blockQuote");
  }
  const characterEscape = {
    name: "characterEscape",
    tokenize: tokenizeCharacterEscape
  };
  function tokenizeCharacterEscape(effects, ok2, nok) {
    return start;
    function start(code2) {
      effects.enter("characterEscape");
      effects.enter("escapeMarker");
      effects.consume(code2);
      effects.exit("escapeMarker");
      return inside;
    }
    function inside(code2) {
      if (asciiPunctuation(code2)) {
        effects.enter("characterEscapeValue");
        effects.consume(code2);
        effects.exit("characterEscapeValue");
        effects.exit("characterEscape");
        return ok2;
      }
      return nok(code2);
    }
  }
  const characterReference = {
    name: "characterReference",
    tokenize: tokenizeCharacterReference
  };
  function tokenizeCharacterReference(effects, ok2, nok) {
    const self2 = this;
    let size = 0;
    let max;
    let test;
    return start;
    function start(code2) {
      effects.enter("characterReference");
      effects.enter("characterReferenceMarker");
      effects.consume(code2);
      effects.exit("characterReferenceMarker");
      return open;
    }
    function open(code2) {
      if (code2 === 35) {
        effects.enter("characterReferenceMarkerNumeric");
        effects.consume(code2);
        effects.exit("characterReferenceMarkerNumeric");
        return numeric;
      }
      effects.enter("characterReferenceValue");
      max = 31;
      test = asciiAlphanumeric;
      return value(code2);
    }
    function numeric(code2) {
      if (code2 === 88 || code2 === 120) {
        effects.enter("characterReferenceMarkerHexadecimal");
        effects.consume(code2);
        effects.exit("characterReferenceMarkerHexadecimal");
        effects.enter("characterReferenceValue");
        max = 6;
        test = asciiHexDigit;
        return value;
      }
      effects.enter("characterReferenceValue");
      max = 7;
      test = asciiDigit;
      return value(code2);
    }
    function value(code2) {
      if (code2 === 59 && size) {
        const token = effects.exit("characterReferenceValue");
        if (test === asciiAlphanumeric && !decodeNamedCharacterReference(self2.sliceSerialize(token))) {
          return nok(code2);
        }
        effects.enter("characterReferenceMarker");
        effects.consume(code2);
        effects.exit("characterReferenceMarker");
        effects.exit("characterReference");
        return ok2;
      }
      if (test(code2) && size++ < max) {
        effects.consume(code2);
        return value;
      }
      return nok(code2);
    }
  }
  const nonLazyContinuation = {
    tokenize: tokenizeNonLazyContinuation,
    partial: true
  };
  const codeFenced = {
    name: "codeFenced",
    tokenize: tokenizeCodeFenced,
    concrete: true
  };
  function tokenizeCodeFenced(effects, ok2, nok) {
    const self2 = this;
    const closeStart = {
      tokenize: tokenizeCloseStart,
      partial: true
    };
    let initialPrefix = 0;
    let sizeOpen = 0;
    let marker;
    return start;
    function start(code2) {
      return beforeSequenceOpen(code2);
    }
    function beforeSequenceOpen(code2) {
      const tail = self2.events[self2.events.length - 1];
      initialPrefix = tail && tail[1].type === "linePrefix" ? tail[2].sliceSerialize(tail[1], true).length : 0;
      marker = code2;
      effects.enter("codeFenced");
      effects.enter("codeFencedFence");
      effects.enter("codeFencedFenceSequence");
      return sequenceOpen(code2);
    }
    function sequenceOpen(code2) {
      if (code2 === marker) {
        sizeOpen++;
        effects.consume(code2);
        return sequenceOpen;
      }
      if (sizeOpen < 3) {
        return nok(code2);
      }
      effects.exit("codeFencedFenceSequence");
      return markdownSpace(code2) ? factorySpace(effects, infoBefore, "whitespace")(code2) : infoBefore(code2);
    }
    function infoBefore(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("codeFencedFence");
        return self2.interrupt ? ok2(code2) : effects.check(nonLazyContinuation, atNonLazyBreak, after)(code2);
      }
      effects.enter("codeFencedFenceInfo");
      effects.enter("chunkString", {
        contentType: "string"
      });
      return info(code2);
    }
    function info(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("chunkString");
        effects.exit("codeFencedFenceInfo");
        return infoBefore(code2);
      }
      if (markdownSpace(code2)) {
        effects.exit("chunkString");
        effects.exit("codeFencedFenceInfo");
        return factorySpace(effects, metaBefore, "whitespace")(code2);
      }
      if (code2 === 96 && code2 === marker) {
        return nok(code2);
      }
      effects.consume(code2);
      return info;
    }
    function metaBefore(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        return infoBefore(code2);
      }
      effects.enter("codeFencedFenceMeta");
      effects.enter("chunkString", {
        contentType: "string"
      });
      return meta(code2);
    }
    function meta(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("chunkString");
        effects.exit("codeFencedFenceMeta");
        return infoBefore(code2);
      }
      if (code2 === 96 && code2 === marker) {
        return nok(code2);
      }
      effects.consume(code2);
      return meta;
    }
    function atNonLazyBreak(code2) {
      return effects.attempt(closeStart, after, contentBefore)(code2);
    }
    function contentBefore(code2) {
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      return contentStart;
    }
    function contentStart(code2) {
      return initialPrefix > 0 && markdownSpace(code2) ? factorySpace(
        effects,
        beforeContentChunk,
        "linePrefix",
        initialPrefix + 1
      )(code2) : beforeContentChunk(code2);
    }
    function beforeContentChunk(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        return effects.check(nonLazyContinuation, atNonLazyBreak, after)(code2);
      }
      effects.enter("codeFlowValue");
      return contentChunk(code2);
    }
    function contentChunk(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("codeFlowValue");
        return beforeContentChunk(code2);
      }
      effects.consume(code2);
      return contentChunk;
    }
    function after(code2) {
      effects.exit("codeFenced");
      return ok2(code2);
    }
    function tokenizeCloseStart(effects2, ok3, nok2) {
      let size = 0;
      return startBefore;
      function startBefore(code2) {
        effects2.enter("lineEnding");
        effects2.consume(code2);
        effects2.exit("lineEnding");
        return start2;
      }
      function start2(code2) {
        effects2.enter("codeFencedFence");
        return markdownSpace(code2) ? factorySpace(
          effects2,
          beforeSequenceClose,
          "linePrefix",
          self2.parser.constructs.disable.null.includes("codeIndented") ? void 0 : 4
        )(code2) : beforeSequenceClose(code2);
      }
      function beforeSequenceClose(code2) {
        if (code2 === marker) {
          effects2.enter("codeFencedFenceSequence");
          return sequenceClose(code2);
        }
        return nok2(code2);
      }
      function sequenceClose(code2) {
        if (code2 === marker) {
          size++;
          effects2.consume(code2);
          return sequenceClose;
        }
        if (size >= sizeOpen) {
          effects2.exit("codeFencedFenceSequence");
          return markdownSpace(code2) ? factorySpace(effects2, sequenceCloseAfter, "whitespace")(code2) : sequenceCloseAfter(code2);
        }
        return nok2(code2);
      }
      function sequenceCloseAfter(code2) {
        if (code2 === null || markdownLineEnding(code2)) {
          effects2.exit("codeFencedFence");
          return ok3(code2);
        }
        return nok2(code2);
      }
    }
  }
  function tokenizeNonLazyContinuation(effects, ok2, nok) {
    const self2 = this;
    return start;
    function start(code2) {
      if (code2 === null) {
        return nok(code2);
      }
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      return lineStart;
    }
    function lineStart(code2) {
      return self2.parser.lazy[self2.now().line] ? nok(code2) : ok2(code2);
    }
  }
  const codeIndented = {
    name: "codeIndented",
    tokenize: tokenizeCodeIndented
  };
  const furtherStart = {
    tokenize: tokenizeFurtherStart,
    partial: true
  };
  function tokenizeCodeIndented(effects, ok2, nok) {
    const self2 = this;
    return start;
    function start(code2) {
      effects.enter("codeIndented");
      return factorySpace(effects, afterPrefix, "linePrefix", 4 + 1)(code2);
    }
    function afterPrefix(code2) {
      const tail = self2.events[self2.events.length - 1];
      return tail && tail[1].type === "linePrefix" && tail[2].sliceSerialize(tail[1], true).length >= 4 ? atBreak(code2) : nok(code2);
    }
    function atBreak(code2) {
      if (code2 === null) {
        return after(code2);
      }
      if (markdownLineEnding(code2)) {
        return effects.attempt(furtherStart, atBreak, after)(code2);
      }
      effects.enter("codeFlowValue");
      return inside(code2);
    }
    function inside(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("codeFlowValue");
        return atBreak(code2);
      }
      effects.consume(code2);
      return inside;
    }
    function after(code2) {
      effects.exit("codeIndented");
      return ok2(code2);
    }
  }
  function tokenizeFurtherStart(effects, ok2, nok) {
    const self2 = this;
    return furtherStart2;
    function furtherStart2(code2) {
      if (self2.parser.lazy[self2.now().line]) {
        return nok(code2);
      }
      if (markdownLineEnding(code2)) {
        effects.enter("lineEnding");
        effects.consume(code2);
        effects.exit("lineEnding");
        return furtherStart2;
      }
      return factorySpace(effects, afterPrefix, "linePrefix", 4 + 1)(code2);
    }
    function afterPrefix(code2) {
      const tail = self2.events[self2.events.length - 1];
      return tail && tail[1].type === "linePrefix" && tail[2].sliceSerialize(tail[1], true).length >= 4 ? ok2(code2) : markdownLineEnding(code2) ? furtherStart2(code2) : nok(code2);
    }
  }
  const codeText = {
    name: "codeText",
    tokenize: tokenizeCodeText,
    resolve: resolveCodeText,
    previous: previous$1
  };
  function resolveCodeText(events) {
    let tailExitIndex = events.length - 4;
    let headEnterIndex = 3;
    let index2;
    let enter;
    if ((events[headEnterIndex][1].type === "lineEnding" || events[headEnterIndex][1].type === "space") && (events[tailExitIndex][1].type === "lineEnding" || events[tailExitIndex][1].type === "space")) {
      index2 = headEnterIndex;
      while (++index2 < tailExitIndex) {
        if (events[index2][1].type === "codeTextData") {
          events[headEnterIndex][1].type = "codeTextPadding";
          events[tailExitIndex][1].type = "codeTextPadding";
          headEnterIndex += 2;
          tailExitIndex -= 2;
          break;
        }
      }
    }
    index2 = headEnterIndex - 1;
    tailExitIndex++;
    while (++index2 <= tailExitIndex) {
      if (enter === void 0) {
        if (index2 !== tailExitIndex && events[index2][1].type !== "lineEnding") {
          enter = index2;
        }
      } else if (index2 === tailExitIndex || events[index2][1].type === "lineEnding") {
        events[enter][1].type = "codeTextData";
        if (index2 !== enter + 2) {
          events[enter][1].end = events[index2 - 1][1].end;
          events.splice(enter + 2, index2 - enter - 2);
          tailExitIndex -= index2 - enter - 2;
          index2 = enter + 2;
        }
        enter = void 0;
      }
    }
    return events;
  }
  function previous$1(code2) {
    return code2 !== 96 || this.events[this.events.length - 1][1].type === "characterEscape";
  }
  function tokenizeCodeText(effects, ok2, nok) {
    let sizeOpen = 0;
    let size;
    let token;
    return start;
    function start(code2) {
      effects.enter("codeText");
      effects.enter("codeTextSequence");
      return sequenceOpen(code2);
    }
    function sequenceOpen(code2) {
      if (code2 === 96) {
        effects.consume(code2);
        sizeOpen++;
        return sequenceOpen;
      }
      effects.exit("codeTextSequence");
      return between(code2);
    }
    function between(code2) {
      if (code2 === null) {
        return nok(code2);
      }
      if (code2 === 32) {
        effects.enter("space");
        effects.consume(code2);
        effects.exit("space");
        return between;
      }
      if (code2 === 96) {
        token = effects.enter("codeTextSequence");
        size = 0;
        return sequenceClose(code2);
      }
      if (markdownLineEnding(code2)) {
        effects.enter("lineEnding");
        effects.consume(code2);
        effects.exit("lineEnding");
        return between;
      }
      effects.enter("codeTextData");
      return data(code2);
    }
    function data(code2) {
      if (code2 === null || code2 === 32 || code2 === 96 || markdownLineEnding(code2)) {
        effects.exit("codeTextData");
        return between(code2);
      }
      effects.consume(code2);
      return data;
    }
    function sequenceClose(code2) {
      if (code2 === 96) {
        effects.consume(code2);
        size++;
        return sequenceClose;
      }
      if (size === sizeOpen) {
        effects.exit("codeTextSequence");
        effects.exit("codeText");
        return ok2(code2);
      }
      token.type = "codeTextData";
      return data(code2);
    }
  }
  function subtokenize(events) {
    const jumps = {};
    let index2 = -1;
    let event;
    let lineIndex;
    let otherIndex;
    let otherEvent;
    let parameters;
    let subevents;
    let more;
    while (++index2 < events.length) {
      while (index2 in jumps) {
        index2 = jumps[index2];
      }
      event = events[index2];
      if (index2 && event[1].type === "chunkFlow" && events[index2 - 1][1].type === "listItemPrefix") {
        subevents = event[1]._tokenizer.events;
        otherIndex = 0;
        if (otherIndex < subevents.length && subevents[otherIndex][1].type === "lineEndingBlank") {
          otherIndex += 2;
        }
        if (otherIndex < subevents.length && subevents[otherIndex][1].type === "content") {
          while (++otherIndex < subevents.length) {
            if (subevents[otherIndex][1].type === "content") {
              break;
            }
            if (subevents[otherIndex][1].type === "chunkText") {
              subevents[otherIndex][1]._isInFirstContentOfListItem = true;
              otherIndex++;
            }
          }
        }
      }
      if (event[0] === "enter") {
        if (event[1].contentType) {
          Object.assign(jumps, subcontent(events, index2));
          index2 = jumps[index2];
          more = true;
        }
      } else if (event[1]._container) {
        otherIndex = index2;
        lineIndex = void 0;
        while (otherIndex--) {
          otherEvent = events[otherIndex];
          if (otherEvent[1].type === "lineEnding" || otherEvent[1].type === "lineEndingBlank") {
            if (otherEvent[0] === "enter") {
              if (lineIndex) {
                events[lineIndex][1].type = "lineEndingBlank";
              }
              otherEvent[1].type = "lineEnding";
              lineIndex = otherIndex;
            }
          } else {
            break;
          }
        }
        if (lineIndex) {
          event[1].end = Object.assign({}, events[lineIndex][1].start);
          parameters = events.slice(lineIndex, index2);
          parameters.unshift(event);
          splice(events, lineIndex, index2 - lineIndex + 1, parameters);
        }
      }
    }
    return !more;
  }
  function subcontent(events, eventIndex) {
    const token = events[eventIndex][1];
    const context = events[eventIndex][2];
    let startPosition = eventIndex - 1;
    const startPositions = [];
    const tokenizer = token._tokenizer || context.parser[token.contentType](token.start);
    const childEvents = tokenizer.events;
    const jumps = [];
    const gaps = {};
    let stream;
    let previous2;
    let index2 = -1;
    let current = token;
    let adjust = 0;
    let start = 0;
    const breaks = [start];
    while (current) {
      while (events[++startPosition][1] !== current) {
      }
      startPositions.push(startPosition);
      if (!current._tokenizer) {
        stream = context.sliceStream(current);
        if (!current.next) {
          stream.push(null);
        }
        if (previous2) {
          tokenizer.defineSkip(current.start);
        }
        if (current._isInFirstContentOfListItem) {
          tokenizer._gfmTasklistFirstContentOfListItem = true;
        }
        tokenizer.write(stream);
        if (current._isInFirstContentOfListItem) {
          tokenizer._gfmTasklistFirstContentOfListItem = void 0;
        }
      }
      previous2 = current;
      current = current.next;
    }
    current = token;
    while (++index2 < childEvents.length) {
      if (
        // Find a void token that includes a break.
        childEvents[index2][0] === "exit" && childEvents[index2 - 1][0] === "enter" && childEvents[index2][1].type === childEvents[index2 - 1][1].type && childEvents[index2][1].start.line !== childEvents[index2][1].end.line
      ) {
        start = index2 + 1;
        breaks.push(start);
        current._tokenizer = void 0;
        current.previous = void 0;
        current = current.next;
      }
    }
    tokenizer.events = [];
    if (current) {
      current._tokenizer = void 0;
      current.previous = void 0;
    } else {
      breaks.pop();
    }
    index2 = breaks.length;
    while (index2--) {
      const slice = childEvents.slice(breaks[index2], breaks[index2 + 1]);
      const start2 = startPositions.pop();
      jumps.unshift([start2, start2 + slice.length - 1]);
      splice(events, start2, 2, slice);
    }
    index2 = -1;
    while (++index2 < jumps.length) {
      gaps[adjust + jumps[index2][0]] = adjust + jumps[index2][1];
      adjust += jumps[index2][1] - jumps[index2][0] - 1;
    }
    return gaps;
  }
  const content = {
    tokenize: tokenizeContent,
    resolve: resolveContent
  };
  const continuationConstruct = {
    tokenize: tokenizeContinuation,
    partial: true
  };
  function resolveContent(events) {
    subtokenize(events);
    return events;
  }
  function tokenizeContent(effects, ok2) {
    let previous2;
    return chunkStart;
    function chunkStart(code2) {
      effects.enter("content");
      previous2 = effects.enter("chunkContent", {
        contentType: "content"
      });
      return chunkInside(code2);
    }
    function chunkInside(code2) {
      if (code2 === null) {
        return contentEnd(code2);
      }
      if (markdownLineEnding(code2)) {
        return effects.check(
          continuationConstruct,
          contentContinue,
          contentEnd
        )(code2);
      }
      effects.consume(code2);
      return chunkInside;
    }
    function contentEnd(code2) {
      effects.exit("chunkContent");
      effects.exit("content");
      return ok2(code2);
    }
    function contentContinue(code2) {
      effects.consume(code2);
      effects.exit("chunkContent");
      previous2.next = effects.enter("chunkContent", {
        contentType: "content",
        previous: previous2
      });
      previous2 = previous2.next;
      return chunkInside;
    }
  }
  function tokenizeContinuation(effects, ok2, nok) {
    const self2 = this;
    return startLookahead;
    function startLookahead(code2) {
      effects.exit("chunkContent");
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      return factorySpace(effects, prefixed, "linePrefix");
    }
    function prefixed(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        return nok(code2);
      }
      const tail = self2.events[self2.events.length - 1];
      if (!self2.parser.constructs.disable.null.includes("codeIndented") && tail && tail[1].type === "linePrefix" && tail[2].sliceSerialize(tail[1], true).length >= 4) {
        return ok2(code2);
      }
      return effects.interrupt(self2.parser.constructs.flow, nok, ok2)(code2);
    }
  }
  function factoryDestination(effects, ok2, nok, type, literalType, literalMarkerType, rawType, stringType, max) {
    const limit = max || Number.POSITIVE_INFINITY;
    let balance = 0;
    return start;
    function start(code2) {
      if (code2 === 60) {
        effects.enter(type);
        effects.enter(literalType);
        effects.enter(literalMarkerType);
        effects.consume(code2);
        effects.exit(literalMarkerType);
        return enclosedBefore;
      }
      if (code2 === null || code2 === 32 || code2 === 41 || asciiControl(code2)) {
        return nok(code2);
      }
      effects.enter(type);
      effects.enter(rawType);
      effects.enter(stringType);
      effects.enter("chunkString", {
        contentType: "string"
      });
      return raw(code2);
    }
    function enclosedBefore(code2) {
      if (code2 === 62) {
        effects.enter(literalMarkerType);
        effects.consume(code2);
        effects.exit(literalMarkerType);
        effects.exit(literalType);
        effects.exit(type);
        return ok2;
      }
      effects.enter(stringType);
      effects.enter("chunkString", {
        contentType: "string"
      });
      return enclosed(code2);
    }
    function enclosed(code2) {
      if (code2 === 62) {
        effects.exit("chunkString");
        effects.exit(stringType);
        return enclosedBefore(code2);
      }
      if (code2 === null || code2 === 60 || markdownLineEnding(code2)) {
        return nok(code2);
      }
      effects.consume(code2);
      return code2 === 92 ? enclosedEscape : enclosed;
    }
    function enclosedEscape(code2) {
      if (code2 === 60 || code2 === 62 || code2 === 92) {
        effects.consume(code2);
        return enclosed;
      }
      return enclosed(code2);
    }
    function raw(code2) {
      if (!balance && (code2 === null || code2 === 41 || markdownLineEndingOrSpace(code2))) {
        effects.exit("chunkString");
        effects.exit(stringType);
        effects.exit(rawType);
        effects.exit(type);
        return ok2(code2);
      }
      if (balance < limit && code2 === 40) {
        effects.consume(code2);
        balance++;
        return raw;
      }
      if (code2 === 41) {
        effects.consume(code2);
        balance--;
        return raw;
      }
      if (code2 === null || code2 === 32 || code2 === 40 || asciiControl(code2)) {
        return nok(code2);
      }
      effects.consume(code2);
      return code2 === 92 ? rawEscape : raw;
    }
    function rawEscape(code2) {
      if (code2 === 40 || code2 === 41 || code2 === 92) {
        effects.consume(code2);
        return raw;
      }
      return raw(code2);
    }
  }
  function factoryLabel(effects, ok2, nok, type, markerType, stringType) {
    const self2 = this;
    let size = 0;
    let seen;
    return start;
    function start(code2) {
      effects.enter(type);
      effects.enter(markerType);
      effects.consume(code2);
      effects.exit(markerType);
      effects.enter(stringType);
      return atBreak;
    }
    function atBreak(code2) {
      if (size > 999 || code2 === null || code2 === 91 || code2 === 93 && !seen || // To do: remove in the future once we’ve switched from
      // `micromark-extension-footnote` to `micromark-extension-gfm-footnote`,
      // which doesn’t need this.
      // Hidden footnotes hook.
      /* c8 ignore next 3 */
      code2 === 94 && !size && "_hiddenFootnoteSupport" in self2.parser.constructs) {
        return nok(code2);
      }
      if (code2 === 93) {
        effects.exit(stringType);
        effects.enter(markerType);
        effects.consume(code2);
        effects.exit(markerType);
        effects.exit(type);
        return ok2;
      }
      if (markdownLineEnding(code2)) {
        effects.enter("lineEnding");
        effects.consume(code2);
        effects.exit("lineEnding");
        return atBreak;
      }
      effects.enter("chunkString", {
        contentType: "string"
      });
      return labelInside(code2);
    }
    function labelInside(code2) {
      if (code2 === null || code2 === 91 || code2 === 93 || markdownLineEnding(code2) || size++ > 999) {
        effects.exit("chunkString");
        return atBreak(code2);
      }
      effects.consume(code2);
      if (!seen) seen = !markdownSpace(code2);
      return code2 === 92 ? labelEscape : labelInside;
    }
    function labelEscape(code2) {
      if (code2 === 91 || code2 === 92 || code2 === 93) {
        effects.consume(code2);
        size++;
        return labelInside;
      }
      return labelInside(code2);
    }
  }
  function factoryTitle(effects, ok2, nok, type, markerType, stringType) {
    let marker;
    return start;
    function start(code2) {
      if (code2 === 34 || code2 === 39 || code2 === 40) {
        effects.enter(type);
        effects.enter(markerType);
        effects.consume(code2);
        effects.exit(markerType);
        marker = code2 === 40 ? 41 : code2;
        return begin;
      }
      return nok(code2);
    }
    function begin(code2) {
      if (code2 === marker) {
        effects.enter(markerType);
        effects.consume(code2);
        effects.exit(markerType);
        effects.exit(type);
        return ok2;
      }
      effects.enter(stringType);
      return atBreak(code2);
    }
    function atBreak(code2) {
      if (code2 === marker) {
        effects.exit(stringType);
        return begin(marker);
      }
      if (code2 === null) {
        return nok(code2);
      }
      if (markdownLineEnding(code2)) {
        effects.enter("lineEnding");
        effects.consume(code2);
        effects.exit("lineEnding");
        return factorySpace(effects, atBreak, "linePrefix");
      }
      effects.enter("chunkString", {
        contentType: "string"
      });
      return inside(code2);
    }
    function inside(code2) {
      if (code2 === marker || code2 === null || markdownLineEnding(code2)) {
        effects.exit("chunkString");
        return atBreak(code2);
      }
      effects.consume(code2);
      return code2 === 92 ? escape : inside;
    }
    function escape(code2) {
      if (code2 === marker || code2 === 92) {
        effects.consume(code2);
        return inside;
      }
      return inside(code2);
    }
  }
  function factoryWhitespace(effects, ok2) {
    let seen;
    return start;
    function start(code2) {
      if (markdownLineEnding(code2)) {
        effects.enter("lineEnding");
        effects.consume(code2);
        effects.exit("lineEnding");
        seen = true;
        return start;
      }
      if (markdownSpace(code2)) {
        return factorySpace(
          effects,
          start,
          seen ? "linePrefix" : "lineSuffix"
        )(code2);
      }
      return ok2(code2);
    }
  }
  const definition$1 = {
    name: "definition",
    tokenize: tokenizeDefinition
  };
  const titleBefore = {
    tokenize: tokenizeTitleBefore,
    partial: true
  };
  function tokenizeDefinition(effects, ok2, nok) {
    const self2 = this;
    let identifier;
    return start;
    function start(code2) {
      effects.enter("definition");
      return before(code2);
    }
    function before(code2) {
      return factoryLabel.call(
        self2,
        effects,
        labelAfter,
        // Note: we don’t need to reset the way `markdown-rs` does.
        nok,
        "definitionLabel",
        "definitionLabelMarker",
        "definitionLabelString"
      )(code2);
    }
    function labelAfter(code2) {
      identifier = normalizeIdentifier(
        self2.sliceSerialize(self2.events[self2.events.length - 1][1]).slice(1, -1)
      );
      if (code2 === 58) {
        effects.enter("definitionMarker");
        effects.consume(code2);
        effects.exit("definitionMarker");
        return markerAfter;
      }
      return nok(code2);
    }
    function markerAfter(code2) {
      return markdownLineEndingOrSpace(code2) ? factoryWhitespace(effects, destinationBefore)(code2) : destinationBefore(code2);
    }
    function destinationBefore(code2) {
      return factoryDestination(
        effects,
        destinationAfter,
        // Note: we don’t need to reset the way `markdown-rs` does.
        nok,
        "definitionDestination",
        "definitionDestinationLiteral",
        "definitionDestinationLiteralMarker",
        "definitionDestinationRaw",
        "definitionDestinationString"
      )(code2);
    }
    function destinationAfter(code2) {
      return effects.attempt(titleBefore, after, after)(code2);
    }
    function after(code2) {
      return markdownSpace(code2) ? factorySpace(effects, afterWhitespace, "whitespace")(code2) : afterWhitespace(code2);
    }
    function afterWhitespace(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("definition");
        self2.parser.defined.push(identifier);
        return ok2(code2);
      }
      return nok(code2);
    }
  }
  function tokenizeTitleBefore(effects, ok2, nok) {
    return titleBefore2;
    function titleBefore2(code2) {
      return markdownLineEndingOrSpace(code2) ? factoryWhitespace(effects, beforeMarker)(code2) : nok(code2);
    }
    function beforeMarker(code2) {
      return factoryTitle(
        effects,
        titleAfter,
        nok,
        "definitionTitle",
        "definitionTitleMarker",
        "definitionTitleString"
      )(code2);
    }
    function titleAfter(code2) {
      return markdownSpace(code2) ? factorySpace(effects, titleAfterOptionalWhitespace, "whitespace")(code2) : titleAfterOptionalWhitespace(code2);
    }
    function titleAfterOptionalWhitespace(code2) {
      return code2 === null || markdownLineEnding(code2) ? ok2(code2) : nok(code2);
    }
  }
  const hardBreakEscape = {
    name: "hardBreakEscape",
    tokenize: tokenizeHardBreakEscape
  };
  function tokenizeHardBreakEscape(effects, ok2, nok) {
    return start;
    function start(code2) {
      effects.enter("hardBreakEscape");
      effects.consume(code2);
      return after;
    }
    function after(code2) {
      if (markdownLineEnding(code2)) {
        effects.exit("hardBreakEscape");
        return ok2(code2);
      }
      return nok(code2);
    }
  }
  const headingAtx = {
    name: "headingAtx",
    tokenize: tokenizeHeadingAtx,
    resolve: resolveHeadingAtx
  };
  function resolveHeadingAtx(events, context) {
    let contentEnd = events.length - 2;
    let contentStart = 3;
    let content2;
    let text2;
    if (events[contentStart][1].type === "whitespace") {
      contentStart += 2;
    }
    if (contentEnd - 2 > contentStart && events[contentEnd][1].type === "whitespace") {
      contentEnd -= 2;
    }
    if (events[contentEnd][1].type === "atxHeadingSequence" && (contentStart === contentEnd - 1 || contentEnd - 4 > contentStart && events[contentEnd - 2][1].type === "whitespace")) {
      contentEnd -= contentStart + 1 === contentEnd ? 2 : 4;
    }
    if (contentEnd > contentStart) {
      content2 = {
        type: "atxHeadingText",
        start: events[contentStart][1].start,
        end: events[contentEnd][1].end
      };
      text2 = {
        type: "chunkText",
        start: events[contentStart][1].start,
        end: events[contentEnd][1].end,
        contentType: "text"
      };
      splice(events, contentStart, contentEnd - contentStart + 1, [
        ["enter", content2, context],
        ["enter", text2, context],
        ["exit", text2, context],
        ["exit", content2, context]
      ]);
    }
    return events;
  }
  function tokenizeHeadingAtx(effects, ok2, nok) {
    let size = 0;
    return start;
    function start(code2) {
      effects.enter("atxHeading");
      return before(code2);
    }
    function before(code2) {
      effects.enter("atxHeadingSequence");
      return sequenceOpen(code2);
    }
    function sequenceOpen(code2) {
      if (code2 === 35 && size++ < 6) {
        effects.consume(code2);
        return sequenceOpen;
      }
      if (code2 === null || markdownLineEndingOrSpace(code2)) {
        effects.exit("atxHeadingSequence");
        return atBreak(code2);
      }
      return nok(code2);
    }
    function atBreak(code2) {
      if (code2 === 35) {
        effects.enter("atxHeadingSequence");
        return sequenceFurther(code2);
      }
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("atxHeading");
        return ok2(code2);
      }
      if (markdownSpace(code2)) {
        return factorySpace(effects, atBreak, "whitespace")(code2);
      }
      effects.enter("atxHeadingText");
      return data(code2);
    }
    function sequenceFurther(code2) {
      if (code2 === 35) {
        effects.consume(code2);
        return sequenceFurther;
      }
      effects.exit("atxHeadingSequence");
      return atBreak(code2);
    }
    function data(code2) {
      if (code2 === null || code2 === 35 || markdownLineEndingOrSpace(code2)) {
        effects.exit("atxHeadingText");
        return atBreak(code2);
      }
      effects.consume(code2);
      return data;
    }
  }
  const htmlBlockNames = [
    "address",
    "article",
    "aside",
    "base",
    "basefont",
    "blockquote",
    "body",
    "caption",
    "center",
    "col",
    "colgroup",
    "dd",
    "details",
    "dialog",
    "dir",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "frame",
    "frameset",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "head",
    "header",
    "hr",
    "html",
    "iframe",
    "legend",
    "li",
    "link",
    "main",
    "menu",
    "menuitem",
    "nav",
    "noframes",
    "ol",
    "optgroup",
    "option",
    "p",
    "param",
    "search",
    "section",
    "summary",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "title",
    "tr",
    "track",
    "ul"
  ];
  const htmlRawNames = ["pre", "script", "style", "textarea"];
  const htmlFlow = {
    name: "htmlFlow",
    tokenize: tokenizeHtmlFlow,
    resolveTo: resolveToHtmlFlow,
    concrete: true
  };
  const blankLineBefore = {
    tokenize: tokenizeBlankLineBefore,
    partial: true
  };
  const nonLazyContinuationStart = {
    tokenize: tokenizeNonLazyContinuationStart,
    partial: true
  };
  function resolveToHtmlFlow(events) {
    let index2 = events.length;
    while (index2--) {
      if (events[index2][0] === "enter" && events[index2][1].type === "htmlFlow") {
        break;
      }
    }
    if (index2 > 1 && events[index2 - 2][1].type === "linePrefix") {
      events[index2][1].start = events[index2 - 2][1].start;
      events[index2 + 1][1].start = events[index2 - 2][1].start;
      events.splice(index2 - 2, 2);
    }
    return events;
  }
  function tokenizeHtmlFlow(effects, ok2, nok) {
    const self2 = this;
    let marker;
    let closingTag;
    let buffer;
    let index2;
    let markerB;
    return start;
    function start(code2) {
      return before(code2);
    }
    function before(code2) {
      effects.enter("htmlFlow");
      effects.enter("htmlFlowData");
      effects.consume(code2);
      return open;
    }
    function open(code2) {
      if (code2 === 33) {
        effects.consume(code2);
        return declarationOpen;
      }
      if (code2 === 47) {
        effects.consume(code2);
        closingTag = true;
        return tagCloseStart;
      }
      if (code2 === 63) {
        effects.consume(code2);
        marker = 3;
        return self2.interrupt ? ok2 : continuationDeclarationInside;
      }
      if (asciiAlpha(code2)) {
        effects.consume(code2);
        buffer = String.fromCharCode(code2);
        return tagName;
      }
      return nok(code2);
    }
    function declarationOpen(code2) {
      if (code2 === 45) {
        effects.consume(code2);
        marker = 2;
        return commentOpenInside;
      }
      if (code2 === 91) {
        effects.consume(code2);
        marker = 5;
        index2 = 0;
        return cdataOpenInside;
      }
      if (asciiAlpha(code2)) {
        effects.consume(code2);
        marker = 4;
        return self2.interrupt ? ok2 : continuationDeclarationInside;
      }
      return nok(code2);
    }
    function commentOpenInside(code2) {
      if (code2 === 45) {
        effects.consume(code2);
        return self2.interrupt ? ok2 : continuationDeclarationInside;
      }
      return nok(code2);
    }
    function cdataOpenInside(code2) {
      const value = "CDATA[";
      if (code2 === value.charCodeAt(index2++)) {
        effects.consume(code2);
        if (index2 === value.length) {
          return self2.interrupt ? ok2 : continuation;
        }
        return cdataOpenInside;
      }
      return nok(code2);
    }
    function tagCloseStart(code2) {
      if (asciiAlpha(code2)) {
        effects.consume(code2);
        buffer = String.fromCharCode(code2);
        return tagName;
      }
      return nok(code2);
    }
    function tagName(code2) {
      if (code2 === null || code2 === 47 || code2 === 62 || markdownLineEndingOrSpace(code2)) {
        const slash = code2 === 47;
        const name2 = buffer.toLowerCase();
        if (!slash && !closingTag && htmlRawNames.includes(name2)) {
          marker = 1;
          return self2.interrupt ? ok2(code2) : continuation(code2);
        }
        if (htmlBlockNames.includes(buffer.toLowerCase())) {
          marker = 6;
          if (slash) {
            effects.consume(code2);
            return basicSelfClosing;
          }
          return self2.interrupt ? ok2(code2) : continuation(code2);
        }
        marker = 7;
        return self2.interrupt && !self2.parser.lazy[self2.now().line] ? nok(code2) : closingTag ? completeClosingTagAfter(code2) : completeAttributeNameBefore(code2);
      }
      if (code2 === 45 || asciiAlphanumeric(code2)) {
        effects.consume(code2);
        buffer += String.fromCharCode(code2);
        return tagName;
      }
      return nok(code2);
    }
    function basicSelfClosing(code2) {
      if (code2 === 62) {
        effects.consume(code2);
        return self2.interrupt ? ok2 : continuation;
      }
      return nok(code2);
    }
    function completeClosingTagAfter(code2) {
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return completeClosingTagAfter;
      }
      return completeEnd(code2);
    }
    function completeAttributeNameBefore(code2) {
      if (code2 === 47) {
        effects.consume(code2);
        return completeEnd;
      }
      if (code2 === 58 || code2 === 95 || asciiAlpha(code2)) {
        effects.consume(code2);
        return completeAttributeName;
      }
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return completeAttributeNameBefore;
      }
      return completeEnd(code2);
    }
    function completeAttributeName(code2) {
      if (code2 === 45 || code2 === 46 || code2 === 58 || code2 === 95 || asciiAlphanumeric(code2)) {
        effects.consume(code2);
        return completeAttributeName;
      }
      return completeAttributeNameAfter(code2);
    }
    function completeAttributeNameAfter(code2) {
      if (code2 === 61) {
        effects.consume(code2);
        return completeAttributeValueBefore;
      }
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return completeAttributeNameAfter;
      }
      return completeAttributeNameBefore(code2);
    }
    function completeAttributeValueBefore(code2) {
      if (code2 === null || code2 === 60 || code2 === 61 || code2 === 62 || code2 === 96) {
        return nok(code2);
      }
      if (code2 === 34 || code2 === 39) {
        effects.consume(code2);
        markerB = code2;
        return completeAttributeValueQuoted;
      }
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return completeAttributeValueBefore;
      }
      return completeAttributeValueUnquoted(code2);
    }
    function completeAttributeValueQuoted(code2) {
      if (code2 === markerB) {
        effects.consume(code2);
        markerB = null;
        return completeAttributeValueQuotedAfter;
      }
      if (code2 === null || markdownLineEnding(code2)) {
        return nok(code2);
      }
      effects.consume(code2);
      return completeAttributeValueQuoted;
    }
    function completeAttributeValueUnquoted(code2) {
      if (code2 === null || code2 === 34 || code2 === 39 || code2 === 47 || code2 === 60 || code2 === 61 || code2 === 62 || code2 === 96 || markdownLineEndingOrSpace(code2)) {
        return completeAttributeNameAfter(code2);
      }
      effects.consume(code2);
      return completeAttributeValueUnquoted;
    }
    function completeAttributeValueQuotedAfter(code2) {
      if (code2 === 47 || code2 === 62 || markdownSpace(code2)) {
        return completeAttributeNameBefore(code2);
      }
      return nok(code2);
    }
    function completeEnd(code2) {
      if (code2 === 62) {
        effects.consume(code2);
        return completeAfter;
      }
      return nok(code2);
    }
    function completeAfter(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        return continuation(code2);
      }
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return completeAfter;
      }
      return nok(code2);
    }
    function continuation(code2) {
      if (code2 === 45 && marker === 2) {
        effects.consume(code2);
        return continuationCommentInside;
      }
      if (code2 === 60 && marker === 1) {
        effects.consume(code2);
        return continuationRawTagOpen;
      }
      if (code2 === 62 && marker === 4) {
        effects.consume(code2);
        return continuationClose;
      }
      if (code2 === 63 && marker === 3) {
        effects.consume(code2);
        return continuationDeclarationInside;
      }
      if (code2 === 93 && marker === 5) {
        effects.consume(code2);
        return continuationCdataInside;
      }
      if (markdownLineEnding(code2) && (marker === 6 || marker === 7)) {
        effects.exit("htmlFlowData");
        return effects.check(
          blankLineBefore,
          continuationAfter,
          continuationStart
        )(code2);
      }
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("htmlFlowData");
        return continuationStart(code2);
      }
      effects.consume(code2);
      return continuation;
    }
    function continuationStart(code2) {
      return effects.check(
        nonLazyContinuationStart,
        continuationStartNonLazy,
        continuationAfter
      )(code2);
    }
    function continuationStartNonLazy(code2) {
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      return continuationBefore;
    }
    function continuationBefore(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        return continuationStart(code2);
      }
      effects.enter("htmlFlowData");
      return continuation(code2);
    }
    function continuationCommentInside(code2) {
      if (code2 === 45) {
        effects.consume(code2);
        return continuationDeclarationInside;
      }
      return continuation(code2);
    }
    function continuationRawTagOpen(code2) {
      if (code2 === 47) {
        effects.consume(code2);
        buffer = "";
        return continuationRawEndTag;
      }
      return continuation(code2);
    }
    function continuationRawEndTag(code2) {
      if (code2 === 62) {
        const name2 = buffer.toLowerCase();
        if (htmlRawNames.includes(name2)) {
          effects.consume(code2);
          return continuationClose;
        }
        return continuation(code2);
      }
      if (asciiAlpha(code2) && buffer.length < 8) {
        effects.consume(code2);
        buffer += String.fromCharCode(code2);
        return continuationRawEndTag;
      }
      return continuation(code2);
    }
    function continuationCdataInside(code2) {
      if (code2 === 93) {
        effects.consume(code2);
        return continuationDeclarationInside;
      }
      return continuation(code2);
    }
    function continuationDeclarationInside(code2) {
      if (code2 === 62) {
        effects.consume(code2);
        return continuationClose;
      }
      if (code2 === 45 && marker === 2) {
        effects.consume(code2);
        return continuationDeclarationInside;
      }
      return continuation(code2);
    }
    function continuationClose(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("htmlFlowData");
        return continuationAfter(code2);
      }
      effects.consume(code2);
      return continuationClose;
    }
    function continuationAfter(code2) {
      effects.exit("htmlFlow");
      return ok2(code2);
    }
  }
  function tokenizeNonLazyContinuationStart(effects, ok2, nok) {
    const self2 = this;
    return start;
    function start(code2) {
      if (markdownLineEnding(code2)) {
        effects.enter("lineEnding");
        effects.consume(code2);
        effects.exit("lineEnding");
        return after;
      }
      return nok(code2);
    }
    function after(code2) {
      return self2.parser.lazy[self2.now().line] ? nok(code2) : ok2(code2);
    }
  }
  function tokenizeBlankLineBefore(effects, ok2, nok) {
    return start;
    function start(code2) {
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      return effects.attempt(blankLine, ok2, nok);
    }
  }
  const htmlText = {
    name: "htmlText",
    tokenize: tokenizeHtmlText
  };
  function tokenizeHtmlText(effects, ok2, nok) {
    const self2 = this;
    let marker;
    let index2;
    let returnState;
    return start;
    function start(code2) {
      effects.enter("htmlText");
      effects.enter("htmlTextData");
      effects.consume(code2);
      return open;
    }
    function open(code2) {
      if (code2 === 33) {
        effects.consume(code2);
        return declarationOpen;
      }
      if (code2 === 47) {
        effects.consume(code2);
        return tagCloseStart;
      }
      if (code2 === 63) {
        effects.consume(code2);
        return instruction;
      }
      if (asciiAlpha(code2)) {
        effects.consume(code2);
        return tagOpen;
      }
      return nok(code2);
    }
    function declarationOpen(code2) {
      if (code2 === 45) {
        effects.consume(code2);
        return commentOpenInside;
      }
      if (code2 === 91) {
        effects.consume(code2);
        index2 = 0;
        return cdataOpenInside;
      }
      if (asciiAlpha(code2)) {
        effects.consume(code2);
        return declaration;
      }
      return nok(code2);
    }
    function commentOpenInside(code2) {
      if (code2 === 45) {
        effects.consume(code2);
        return commentEnd;
      }
      return nok(code2);
    }
    function comment(code2) {
      if (code2 === null) {
        return nok(code2);
      }
      if (code2 === 45) {
        effects.consume(code2);
        return commentClose;
      }
      if (markdownLineEnding(code2)) {
        returnState = comment;
        return lineEndingBefore(code2);
      }
      effects.consume(code2);
      return comment;
    }
    function commentClose(code2) {
      if (code2 === 45) {
        effects.consume(code2);
        return commentEnd;
      }
      return comment(code2);
    }
    function commentEnd(code2) {
      return code2 === 62 ? end(code2) : code2 === 45 ? commentClose(code2) : comment(code2);
    }
    function cdataOpenInside(code2) {
      const value = "CDATA[";
      if (code2 === value.charCodeAt(index2++)) {
        effects.consume(code2);
        return index2 === value.length ? cdata : cdataOpenInside;
      }
      return nok(code2);
    }
    function cdata(code2) {
      if (code2 === null) {
        return nok(code2);
      }
      if (code2 === 93) {
        effects.consume(code2);
        return cdataClose;
      }
      if (markdownLineEnding(code2)) {
        returnState = cdata;
        return lineEndingBefore(code2);
      }
      effects.consume(code2);
      return cdata;
    }
    function cdataClose(code2) {
      if (code2 === 93) {
        effects.consume(code2);
        return cdataEnd;
      }
      return cdata(code2);
    }
    function cdataEnd(code2) {
      if (code2 === 62) {
        return end(code2);
      }
      if (code2 === 93) {
        effects.consume(code2);
        return cdataEnd;
      }
      return cdata(code2);
    }
    function declaration(code2) {
      if (code2 === null || code2 === 62) {
        return end(code2);
      }
      if (markdownLineEnding(code2)) {
        returnState = declaration;
        return lineEndingBefore(code2);
      }
      effects.consume(code2);
      return declaration;
    }
    function instruction(code2) {
      if (code2 === null) {
        return nok(code2);
      }
      if (code2 === 63) {
        effects.consume(code2);
        return instructionClose;
      }
      if (markdownLineEnding(code2)) {
        returnState = instruction;
        return lineEndingBefore(code2);
      }
      effects.consume(code2);
      return instruction;
    }
    function instructionClose(code2) {
      return code2 === 62 ? end(code2) : instruction(code2);
    }
    function tagCloseStart(code2) {
      if (asciiAlpha(code2)) {
        effects.consume(code2);
        return tagClose;
      }
      return nok(code2);
    }
    function tagClose(code2) {
      if (code2 === 45 || asciiAlphanumeric(code2)) {
        effects.consume(code2);
        return tagClose;
      }
      return tagCloseBetween(code2);
    }
    function tagCloseBetween(code2) {
      if (markdownLineEnding(code2)) {
        returnState = tagCloseBetween;
        return lineEndingBefore(code2);
      }
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return tagCloseBetween;
      }
      return end(code2);
    }
    function tagOpen(code2) {
      if (code2 === 45 || asciiAlphanumeric(code2)) {
        effects.consume(code2);
        return tagOpen;
      }
      if (code2 === 47 || code2 === 62 || markdownLineEndingOrSpace(code2)) {
        return tagOpenBetween(code2);
      }
      return nok(code2);
    }
    function tagOpenBetween(code2) {
      if (code2 === 47) {
        effects.consume(code2);
        return end;
      }
      if (code2 === 58 || code2 === 95 || asciiAlpha(code2)) {
        effects.consume(code2);
        return tagOpenAttributeName;
      }
      if (markdownLineEnding(code2)) {
        returnState = tagOpenBetween;
        return lineEndingBefore(code2);
      }
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return tagOpenBetween;
      }
      return end(code2);
    }
    function tagOpenAttributeName(code2) {
      if (code2 === 45 || code2 === 46 || code2 === 58 || code2 === 95 || asciiAlphanumeric(code2)) {
        effects.consume(code2);
        return tagOpenAttributeName;
      }
      return tagOpenAttributeNameAfter(code2);
    }
    function tagOpenAttributeNameAfter(code2) {
      if (code2 === 61) {
        effects.consume(code2);
        return tagOpenAttributeValueBefore;
      }
      if (markdownLineEnding(code2)) {
        returnState = tagOpenAttributeNameAfter;
        return lineEndingBefore(code2);
      }
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return tagOpenAttributeNameAfter;
      }
      return tagOpenBetween(code2);
    }
    function tagOpenAttributeValueBefore(code2) {
      if (code2 === null || code2 === 60 || code2 === 61 || code2 === 62 || code2 === 96) {
        return nok(code2);
      }
      if (code2 === 34 || code2 === 39) {
        effects.consume(code2);
        marker = code2;
        return tagOpenAttributeValueQuoted;
      }
      if (markdownLineEnding(code2)) {
        returnState = tagOpenAttributeValueBefore;
        return lineEndingBefore(code2);
      }
      if (markdownSpace(code2)) {
        effects.consume(code2);
        return tagOpenAttributeValueBefore;
      }
      effects.consume(code2);
      return tagOpenAttributeValueUnquoted;
    }
    function tagOpenAttributeValueQuoted(code2) {
      if (code2 === marker) {
        effects.consume(code2);
        marker = void 0;
        return tagOpenAttributeValueQuotedAfter;
      }
      if (code2 === null) {
        return nok(code2);
      }
      if (markdownLineEnding(code2)) {
        returnState = tagOpenAttributeValueQuoted;
        return lineEndingBefore(code2);
      }
      effects.consume(code2);
      return tagOpenAttributeValueQuoted;
    }
    function tagOpenAttributeValueUnquoted(code2) {
      if (code2 === null || code2 === 34 || code2 === 39 || code2 === 60 || code2 === 61 || code2 === 96) {
        return nok(code2);
      }
      if (code2 === 47 || code2 === 62 || markdownLineEndingOrSpace(code2)) {
        return tagOpenBetween(code2);
      }
      effects.consume(code2);
      return tagOpenAttributeValueUnquoted;
    }
    function tagOpenAttributeValueQuotedAfter(code2) {
      if (code2 === 47 || code2 === 62 || markdownLineEndingOrSpace(code2)) {
        return tagOpenBetween(code2);
      }
      return nok(code2);
    }
    function end(code2) {
      if (code2 === 62) {
        effects.consume(code2);
        effects.exit("htmlTextData");
        effects.exit("htmlText");
        return ok2;
      }
      return nok(code2);
    }
    function lineEndingBefore(code2) {
      effects.exit("htmlTextData");
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      return lineEndingAfter;
    }
    function lineEndingAfter(code2) {
      return markdownSpace(code2) ? factorySpace(
        effects,
        lineEndingAfterPrefix,
        "linePrefix",
        self2.parser.constructs.disable.null.includes("codeIndented") ? void 0 : 4
      )(code2) : lineEndingAfterPrefix(code2);
    }
    function lineEndingAfterPrefix(code2) {
      effects.enter("htmlTextData");
      return returnState(code2);
    }
  }
  const labelEnd = {
    name: "labelEnd",
    tokenize: tokenizeLabelEnd,
    resolveTo: resolveToLabelEnd,
    resolveAll: resolveAllLabelEnd
  };
  const resourceConstruct = {
    tokenize: tokenizeResource
  };
  const referenceFullConstruct = {
    tokenize: tokenizeReferenceFull
  };
  const referenceCollapsedConstruct = {
    tokenize: tokenizeReferenceCollapsed
  };
  function resolveAllLabelEnd(events) {
    let index2 = -1;
    while (++index2 < events.length) {
      const token = events[index2][1];
      if (token.type === "labelImage" || token.type === "labelLink" || token.type === "labelEnd") {
        events.splice(index2 + 1, token.type === "labelImage" ? 4 : 2);
        token.type = "data";
        index2++;
      }
    }
    return events;
  }
  function resolveToLabelEnd(events, context) {
    let index2 = events.length;
    let offset = 0;
    let token;
    let open;
    let close;
    let media;
    while (index2--) {
      token = events[index2][1];
      if (open) {
        if (token.type === "link" || token.type === "labelLink" && token._inactive) {
          break;
        }
        if (events[index2][0] === "enter" && token.type === "labelLink") {
          token._inactive = true;
        }
      } else if (close) {
        if (events[index2][0] === "enter" && (token.type === "labelImage" || token.type === "labelLink") && !token._balanced) {
          open = index2;
          if (token.type !== "labelLink") {
            offset = 2;
            break;
          }
        }
      } else if (token.type === "labelEnd") {
        close = index2;
      }
    }
    const group = {
      type: events[open][1].type === "labelLink" ? "link" : "image",
      start: Object.assign({}, events[open][1].start),
      end: Object.assign({}, events[events.length - 1][1].end)
    };
    const label = {
      type: "label",
      start: Object.assign({}, events[open][1].start),
      end: Object.assign({}, events[close][1].end)
    };
    const text2 = {
      type: "labelText",
      start: Object.assign({}, events[open + offset + 2][1].end),
      end: Object.assign({}, events[close - 2][1].start)
    };
    media = [
      ["enter", group, context],
      ["enter", label, context]
    ];
    media = push(media, events.slice(open + 1, open + offset + 3));
    media = push(media, [["enter", text2, context]]);
    media = push(
      media,
      resolveAll(
        context.parser.constructs.insideSpan.null,
        events.slice(open + offset + 4, close - 3),
        context
      )
    );
    media = push(media, [
      ["exit", text2, context],
      events[close - 2],
      events[close - 1],
      ["exit", label, context]
    ]);
    media = push(media, events.slice(close + 1));
    media = push(media, [["exit", group, context]]);
    splice(events, open, events.length, media);
    return events;
  }
  function tokenizeLabelEnd(effects, ok2, nok) {
    const self2 = this;
    let index2 = self2.events.length;
    let labelStart;
    let defined;
    while (index2--) {
      if ((self2.events[index2][1].type === "labelImage" || self2.events[index2][1].type === "labelLink") && !self2.events[index2][1]._balanced) {
        labelStart = self2.events[index2][1];
        break;
      }
    }
    return start;
    function start(code2) {
      if (!labelStart) {
        return nok(code2);
      }
      if (labelStart._inactive) {
        return labelEndNok(code2);
      }
      defined = self2.parser.defined.includes(
        normalizeIdentifier(
          self2.sliceSerialize({
            start: labelStart.end,
            end: self2.now()
          })
        )
      );
      effects.enter("labelEnd");
      effects.enter("labelMarker");
      effects.consume(code2);
      effects.exit("labelMarker");
      effects.exit("labelEnd");
      return after;
    }
    function after(code2) {
      if (code2 === 40) {
        return effects.attempt(
          resourceConstruct,
          labelEndOk,
          defined ? labelEndOk : labelEndNok
        )(code2);
      }
      if (code2 === 91) {
        return effects.attempt(
          referenceFullConstruct,
          labelEndOk,
          defined ? referenceNotFull : labelEndNok
        )(code2);
      }
      return defined ? labelEndOk(code2) : labelEndNok(code2);
    }
    function referenceNotFull(code2) {
      return effects.attempt(
        referenceCollapsedConstruct,
        labelEndOk,
        labelEndNok
      )(code2);
    }
    function labelEndOk(code2) {
      return ok2(code2);
    }
    function labelEndNok(code2) {
      labelStart._balanced = true;
      return nok(code2);
    }
  }
  function tokenizeResource(effects, ok2, nok) {
    return resourceStart;
    function resourceStart(code2) {
      effects.enter("resource");
      effects.enter("resourceMarker");
      effects.consume(code2);
      effects.exit("resourceMarker");
      return resourceBefore;
    }
    function resourceBefore(code2) {
      return markdownLineEndingOrSpace(code2) ? factoryWhitespace(effects, resourceOpen)(code2) : resourceOpen(code2);
    }
    function resourceOpen(code2) {
      if (code2 === 41) {
        return resourceEnd(code2);
      }
      return factoryDestination(
        effects,
        resourceDestinationAfter,
        resourceDestinationMissing,
        "resourceDestination",
        "resourceDestinationLiteral",
        "resourceDestinationLiteralMarker",
        "resourceDestinationRaw",
        "resourceDestinationString",
        32
      )(code2);
    }
    function resourceDestinationAfter(code2) {
      return markdownLineEndingOrSpace(code2) ? factoryWhitespace(effects, resourceBetween)(code2) : resourceEnd(code2);
    }
    function resourceDestinationMissing(code2) {
      return nok(code2);
    }
    function resourceBetween(code2) {
      if (code2 === 34 || code2 === 39 || code2 === 40) {
        return factoryTitle(
          effects,
          resourceTitleAfter,
          nok,
          "resourceTitle",
          "resourceTitleMarker",
          "resourceTitleString"
        )(code2);
      }
      return resourceEnd(code2);
    }
    function resourceTitleAfter(code2) {
      return markdownLineEndingOrSpace(code2) ? factoryWhitespace(effects, resourceEnd)(code2) : resourceEnd(code2);
    }
    function resourceEnd(code2) {
      if (code2 === 41) {
        effects.enter("resourceMarker");
        effects.consume(code2);
        effects.exit("resourceMarker");
        effects.exit("resource");
        return ok2;
      }
      return nok(code2);
    }
  }
  function tokenizeReferenceFull(effects, ok2, nok) {
    const self2 = this;
    return referenceFull;
    function referenceFull(code2) {
      return factoryLabel.call(
        self2,
        effects,
        referenceFullAfter,
        referenceFullMissing,
        "reference",
        "referenceMarker",
        "referenceString"
      )(code2);
    }
    function referenceFullAfter(code2) {
      return self2.parser.defined.includes(
        normalizeIdentifier(
          self2.sliceSerialize(self2.events[self2.events.length - 1][1]).slice(1, -1)
        )
      ) ? ok2(code2) : nok(code2);
    }
    function referenceFullMissing(code2) {
      return nok(code2);
    }
  }
  function tokenizeReferenceCollapsed(effects, ok2, nok) {
    return referenceCollapsedStart;
    function referenceCollapsedStart(code2) {
      effects.enter("reference");
      effects.enter("referenceMarker");
      effects.consume(code2);
      effects.exit("referenceMarker");
      return referenceCollapsedOpen;
    }
    function referenceCollapsedOpen(code2) {
      if (code2 === 93) {
        effects.enter("referenceMarker");
        effects.consume(code2);
        effects.exit("referenceMarker");
        effects.exit("reference");
        return ok2;
      }
      return nok(code2);
    }
  }
  const labelStartImage = {
    name: "labelStartImage",
    tokenize: tokenizeLabelStartImage,
    resolveAll: labelEnd.resolveAll
  };
  function tokenizeLabelStartImage(effects, ok2, nok) {
    const self2 = this;
    return start;
    function start(code2) {
      effects.enter("labelImage");
      effects.enter("labelImageMarker");
      effects.consume(code2);
      effects.exit("labelImageMarker");
      return open;
    }
    function open(code2) {
      if (code2 === 91) {
        effects.enter("labelMarker");
        effects.consume(code2);
        effects.exit("labelMarker");
        effects.exit("labelImage");
        return after;
      }
      return nok(code2);
    }
    function after(code2) {
      return code2 === 94 && "_hiddenFootnoteSupport" in self2.parser.constructs ? nok(code2) : ok2(code2);
    }
  }
  const labelStartLink = {
    name: "labelStartLink",
    tokenize: tokenizeLabelStartLink,
    resolveAll: labelEnd.resolveAll
  };
  function tokenizeLabelStartLink(effects, ok2, nok) {
    const self2 = this;
    return start;
    function start(code2) {
      effects.enter("labelLink");
      effects.enter("labelMarker");
      effects.consume(code2);
      effects.exit("labelMarker");
      effects.exit("labelLink");
      return after;
    }
    function after(code2) {
      return code2 === 94 && "_hiddenFootnoteSupport" in self2.parser.constructs ? nok(code2) : ok2(code2);
    }
  }
  const lineEnding = {
    name: "lineEnding",
    tokenize: tokenizeLineEnding
  };
  function tokenizeLineEnding(effects, ok2) {
    return start;
    function start(code2) {
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      return factorySpace(effects, ok2, "linePrefix");
    }
  }
  const thematicBreak$2 = {
    name: "thematicBreak",
    tokenize: tokenizeThematicBreak
  };
  function tokenizeThematicBreak(effects, ok2, nok) {
    let size = 0;
    let marker;
    return start;
    function start(code2) {
      effects.enter("thematicBreak");
      return before(code2);
    }
    function before(code2) {
      marker = code2;
      return atBreak(code2);
    }
    function atBreak(code2) {
      if (code2 === marker) {
        effects.enter("thematicBreakSequence");
        return sequence(code2);
      }
      if (size >= 3 && (code2 === null || markdownLineEnding(code2))) {
        effects.exit("thematicBreak");
        return ok2(code2);
      }
      return nok(code2);
    }
    function sequence(code2) {
      if (code2 === marker) {
        effects.consume(code2);
        size++;
        return sequence;
      }
      effects.exit("thematicBreakSequence");
      return markdownSpace(code2) ? factorySpace(effects, atBreak, "whitespace")(code2) : atBreak(code2);
    }
  }
  const list$2 = {
    name: "list",
    tokenize: tokenizeListStart,
    continuation: {
      tokenize: tokenizeListContinuation
    },
    exit: tokenizeListEnd
  };
  const listItemPrefixWhitespaceConstruct = {
    tokenize: tokenizeListItemPrefixWhitespace,
    partial: true
  };
  const indentConstruct = {
    tokenize: tokenizeIndent$1,
    partial: true
  };
  function tokenizeListStart(effects, ok2, nok) {
    const self2 = this;
    const tail = self2.events[self2.events.length - 1];
    let initialSize = tail && tail[1].type === "linePrefix" ? tail[2].sliceSerialize(tail[1], true).length : 0;
    let size = 0;
    return start;
    function start(code2) {
      const kind = self2.containerState.type || (code2 === 42 || code2 === 43 || code2 === 45 ? "listUnordered" : "listOrdered");
      if (kind === "listUnordered" ? !self2.containerState.marker || code2 === self2.containerState.marker : asciiDigit(code2)) {
        if (!self2.containerState.type) {
          self2.containerState.type = kind;
          effects.enter(kind, {
            _container: true
          });
        }
        if (kind === "listUnordered") {
          effects.enter("listItemPrefix");
          return code2 === 42 || code2 === 45 ? effects.check(thematicBreak$2, nok, atMarker)(code2) : atMarker(code2);
        }
        if (!self2.interrupt || code2 === 49) {
          effects.enter("listItemPrefix");
          effects.enter("listItemValue");
          return inside(code2);
        }
      }
      return nok(code2);
    }
    function inside(code2) {
      if (asciiDigit(code2) && ++size < 10) {
        effects.consume(code2);
        return inside;
      }
      if ((!self2.interrupt || size < 2) && (self2.containerState.marker ? code2 === self2.containerState.marker : code2 === 41 || code2 === 46)) {
        effects.exit("listItemValue");
        return atMarker(code2);
      }
      return nok(code2);
    }
    function atMarker(code2) {
      effects.enter("listItemMarker");
      effects.consume(code2);
      effects.exit("listItemMarker");
      self2.containerState.marker = self2.containerState.marker || code2;
      return effects.check(
        blankLine,
        // Can’t be empty when interrupting.
        self2.interrupt ? nok : onBlank,
        effects.attempt(
          listItemPrefixWhitespaceConstruct,
          endOfPrefix,
          otherPrefix
        )
      );
    }
    function onBlank(code2) {
      self2.containerState.initialBlankLine = true;
      initialSize++;
      return endOfPrefix(code2);
    }
    function otherPrefix(code2) {
      if (markdownSpace(code2)) {
        effects.enter("listItemPrefixWhitespace");
        effects.consume(code2);
        effects.exit("listItemPrefixWhitespace");
        return endOfPrefix;
      }
      return nok(code2);
    }
    function endOfPrefix(code2) {
      self2.containerState.size = initialSize + self2.sliceSerialize(effects.exit("listItemPrefix"), true).length;
      return ok2(code2);
    }
  }
  function tokenizeListContinuation(effects, ok2, nok) {
    const self2 = this;
    self2.containerState._closeFlow = void 0;
    return effects.check(blankLine, onBlank, notBlank);
    function onBlank(code2) {
      self2.containerState.furtherBlankLines = self2.containerState.furtherBlankLines || self2.containerState.initialBlankLine;
      return factorySpace(
        effects,
        ok2,
        "listItemIndent",
        self2.containerState.size + 1
      )(code2);
    }
    function notBlank(code2) {
      if (self2.containerState.furtherBlankLines || !markdownSpace(code2)) {
        self2.containerState.furtherBlankLines = void 0;
        self2.containerState.initialBlankLine = void 0;
        return notInCurrentItem(code2);
      }
      self2.containerState.furtherBlankLines = void 0;
      self2.containerState.initialBlankLine = void 0;
      return effects.attempt(indentConstruct, ok2, notInCurrentItem)(code2);
    }
    function notInCurrentItem(code2) {
      self2.containerState._closeFlow = true;
      self2.interrupt = void 0;
      return factorySpace(
        effects,
        effects.attempt(list$2, ok2, nok),
        "linePrefix",
        self2.parser.constructs.disable.null.includes("codeIndented") ? void 0 : 4
      )(code2);
    }
  }
  function tokenizeIndent$1(effects, ok2, nok) {
    const self2 = this;
    return factorySpace(
      effects,
      afterPrefix,
      "listItemIndent",
      self2.containerState.size + 1
    );
    function afterPrefix(code2) {
      const tail = self2.events[self2.events.length - 1];
      return tail && tail[1].type === "listItemIndent" && tail[2].sliceSerialize(tail[1], true).length === self2.containerState.size ? ok2(code2) : nok(code2);
    }
  }
  function tokenizeListEnd(effects) {
    effects.exit(this.containerState.type);
  }
  function tokenizeListItemPrefixWhitespace(effects, ok2, nok) {
    const self2 = this;
    return factorySpace(
      effects,
      afterPrefix,
      "listItemPrefixWhitespace",
      self2.parser.constructs.disable.null.includes("codeIndented") ? void 0 : 4 + 1
    );
    function afterPrefix(code2) {
      const tail = self2.events[self2.events.length - 1];
      return !markdownSpace(code2) && tail && tail[1].type === "listItemPrefixWhitespace" ? ok2(code2) : nok(code2);
    }
  }
  const setextUnderline = {
    name: "setextUnderline",
    tokenize: tokenizeSetextUnderline,
    resolveTo: resolveToSetextUnderline
  };
  function resolveToSetextUnderline(events, context) {
    let index2 = events.length;
    let content2;
    let text2;
    let definition2;
    while (index2--) {
      if (events[index2][0] === "enter") {
        if (events[index2][1].type === "content") {
          content2 = index2;
          break;
        }
        if (events[index2][1].type === "paragraph") {
          text2 = index2;
        }
      } else {
        if (events[index2][1].type === "content") {
          events.splice(index2, 1);
        }
        if (!definition2 && events[index2][1].type === "definition") {
          definition2 = index2;
        }
      }
    }
    const heading2 = {
      type: "setextHeading",
      start: Object.assign({}, events[text2][1].start),
      end: Object.assign({}, events[events.length - 1][1].end)
    };
    events[text2][1].type = "setextHeadingText";
    if (definition2) {
      events.splice(text2, 0, ["enter", heading2, context]);
      events.splice(definition2 + 1, 0, ["exit", events[content2][1], context]);
      events[content2][1].end = Object.assign({}, events[definition2][1].end);
    } else {
      events[content2][1] = heading2;
    }
    events.push(["exit", heading2, context]);
    return events;
  }
  function tokenizeSetextUnderline(effects, ok2, nok) {
    const self2 = this;
    let marker;
    return start;
    function start(code2) {
      let index2 = self2.events.length;
      let paragraph2;
      while (index2--) {
        if (self2.events[index2][1].type !== "lineEnding" && self2.events[index2][1].type !== "linePrefix" && self2.events[index2][1].type !== "content") {
          paragraph2 = self2.events[index2][1].type === "paragraph";
          break;
        }
      }
      if (!self2.parser.lazy[self2.now().line] && (self2.interrupt || paragraph2)) {
        effects.enter("setextHeadingLine");
        marker = code2;
        return before(code2);
      }
      return nok(code2);
    }
    function before(code2) {
      effects.enter("setextHeadingLineSequence");
      return inside(code2);
    }
    function inside(code2) {
      if (code2 === marker) {
        effects.consume(code2);
        return inside;
      }
      effects.exit("setextHeadingLineSequence");
      return markdownSpace(code2) ? factorySpace(effects, after, "lineSuffix")(code2) : after(code2);
    }
    function after(code2) {
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("setextHeadingLine");
        return ok2(code2);
      }
      return nok(code2);
    }
  }
  const flow$1 = {
    tokenize: initializeFlow
  };
  function initializeFlow(effects) {
    const self2 = this;
    const initial = effects.attempt(
      // Try to parse a blank line.
      blankLine,
      atBlankEnding,
      // Try to parse initial flow (essentially, only code).
      effects.attempt(
        this.parser.constructs.flowInitial,
        afterConstruct,
        factorySpace(
          effects,
          effects.attempt(
            this.parser.constructs.flow,
            afterConstruct,
            effects.attempt(content, afterConstruct)
          ),
          "linePrefix"
        )
      )
    );
    return initial;
    function atBlankEnding(code2) {
      if (code2 === null) {
        effects.consume(code2);
        return;
      }
      effects.enter("lineEndingBlank");
      effects.consume(code2);
      effects.exit("lineEndingBlank");
      self2.currentConstruct = void 0;
      return initial;
    }
    function afterConstruct(code2) {
      if (code2 === null) {
        effects.consume(code2);
        return;
      }
      effects.enter("lineEnding");
      effects.consume(code2);
      effects.exit("lineEnding");
      self2.currentConstruct = void 0;
      return initial;
    }
  }
  const resolver = {
    resolveAll: createResolver()
  };
  const string$1 = initializeFactory("string");
  const text$4 = initializeFactory("text");
  function initializeFactory(field) {
    return {
      tokenize: initializeText,
      resolveAll: createResolver(
        field === "text" ? resolveAllLineSuffixes : void 0
      )
    };
    function initializeText(effects) {
      const self2 = this;
      const constructs2 = this.parser.constructs[field];
      const text2 = effects.attempt(constructs2, start, notText);
      return start;
      function start(code2) {
        return atBreak(code2) ? text2(code2) : notText(code2);
      }
      function notText(code2) {
        if (code2 === null) {
          effects.consume(code2);
          return;
        }
        effects.enter("data");
        effects.consume(code2);
        return data;
      }
      function data(code2) {
        if (atBreak(code2)) {
          effects.exit("data");
          return text2(code2);
        }
        effects.consume(code2);
        return data;
      }
      function atBreak(code2) {
        if (code2 === null) {
          return true;
        }
        const list2 = constructs2[code2];
        let index2 = -1;
        if (list2) {
          while (++index2 < list2.length) {
            const item = list2[index2];
            if (!item.previous || item.previous.call(self2, self2.previous)) {
              return true;
            }
          }
        }
        return false;
      }
    }
  }
  function createResolver(extraResolver) {
    return resolveAllText;
    function resolveAllText(events, context) {
      let index2 = -1;
      let enter;
      while (++index2 <= events.length) {
        if (enter === void 0) {
          if (events[index2] && events[index2][1].type === "data") {
            enter = index2;
            index2++;
          }
        } else if (!events[index2] || events[index2][1].type !== "data") {
          if (index2 !== enter + 2) {
            events[enter][1].end = events[index2 - 1][1].end;
            events.splice(enter + 2, index2 - enter - 2);
            index2 = enter + 2;
          }
          enter = void 0;
        }
      }
      return extraResolver ? extraResolver(events, context) : events;
    }
  }
  function resolveAllLineSuffixes(events, context) {
    let eventIndex = 0;
    while (++eventIndex <= events.length) {
      if ((eventIndex === events.length || events[eventIndex][1].type === "lineEnding") && events[eventIndex - 1][1].type === "data") {
        const data = events[eventIndex - 1][1];
        const chunks = context.sliceStream(data);
        let index2 = chunks.length;
        let bufferIndex = -1;
        let size = 0;
        let tabs;
        while (index2--) {
          const chunk = chunks[index2];
          if (typeof chunk === "string") {
            bufferIndex = chunk.length;
            while (chunk.charCodeAt(bufferIndex - 1) === 32) {
              size++;
              bufferIndex--;
            }
            if (bufferIndex) break;
            bufferIndex = -1;
          } else if (chunk === -2) {
            tabs = true;
            size++;
          } else if (chunk === -1) ;
          else {
            index2++;
            break;
          }
        }
        if (size) {
          const token = {
            type: eventIndex === events.length || tabs || size < 2 ? "lineSuffix" : "hardBreakTrailing",
            start: {
              line: data.end.line,
              column: data.end.column - size,
              offset: data.end.offset - size,
              _index: data.start._index + index2,
              _bufferIndex: index2 ? bufferIndex : data.start._bufferIndex + bufferIndex
            },
            end: Object.assign({}, data.end)
          };
          data.end = Object.assign({}, token.start);
          if (data.start.offset === data.end.offset) {
            Object.assign(data, token);
          } else {
            events.splice(
              eventIndex,
              0,
              ["enter", token, context],
              ["exit", token, context]
            );
            eventIndex += 2;
          }
        }
        eventIndex++;
      }
    }
    return events;
  }
  function createTokenizer(parser, initialize, from) {
    let point2 = Object.assign(
      from ? Object.assign({}, from) : {
        line: 1,
        column: 1,
        offset: 0
      },
      {
        _index: 0,
        _bufferIndex: -1
      }
    );
    const columnStart = {};
    const resolveAllConstructs = [];
    let chunks = [];
    let stack = [];
    const effects = {
      consume,
      enter,
      exit: exit2,
      attempt: constructFactory(onsuccessfulconstruct),
      check: constructFactory(onsuccessfulcheck),
      interrupt: constructFactory(onsuccessfulcheck, {
        interrupt: true
      })
    };
    const context = {
      previous: null,
      code: null,
      containerState: {},
      events: [],
      parser,
      sliceStream,
      sliceSerialize,
      now,
      defineSkip,
      write
    };
    let state = initialize.tokenize.call(context, effects);
    if (initialize.resolveAll) {
      resolveAllConstructs.push(initialize);
    }
    return context;
    function write(slice) {
      chunks = push(chunks, slice);
      main();
      if (chunks[chunks.length - 1] !== null) {
        return [];
      }
      addResult(initialize, 0);
      context.events = resolveAll(resolveAllConstructs, context.events, context);
      return context.events;
    }
    function sliceSerialize(token, expandTabs) {
      return serializeChunks(sliceStream(token), expandTabs);
    }
    function sliceStream(token) {
      return sliceChunks(chunks, token);
    }
    function now() {
      const { line, column, offset, _index, _bufferIndex } = point2;
      return {
        line,
        column,
        offset,
        _index,
        _bufferIndex
      };
    }
    function defineSkip(value) {
      columnStart[value.line] = value.column;
      accountForPotentialSkip();
    }
    function main() {
      let chunkIndex;
      while (point2._index < chunks.length) {
        const chunk = chunks[point2._index];
        if (typeof chunk === "string") {
          chunkIndex = point2._index;
          if (point2._bufferIndex < 0) {
            point2._bufferIndex = 0;
          }
          while (point2._index === chunkIndex && point2._bufferIndex < chunk.length) {
            go(chunk.charCodeAt(point2._bufferIndex));
          }
        } else {
          go(chunk);
        }
      }
    }
    function go(code2) {
      state = state(code2);
    }
    function consume(code2) {
      if (markdownLineEnding(code2)) {
        point2.line++;
        point2.column = 1;
        point2.offset += code2 === -3 ? 2 : 1;
        accountForPotentialSkip();
      } else if (code2 !== -1) {
        point2.column++;
        point2.offset++;
      }
      if (point2._bufferIndex < 0) {
        point2._index++;
      } else {
        point2._bufferIndex++;
        if (point2._bufferIndex === chunks[point2._index].length) {
          point2._bufferIndex = -1;
          point2._index++;
        }
      }
      context.previous = code2;
    }
    function enter(type, fields) {
      const token = fields || {};
      token.type = type;
      token.start = now();
      context.events.push(["enter", token, context]);
      stack.push(token);
      return token;
    }
    function exit2(type) {
      const token = stack.pop();
      token.end = now();
      context.events.push(["exit", token, context]);
      return token;
    }
    function onsuccessfulconstruct(construct, info) {
      addResult(construct, info.from);
    }
    function onsuccessfulcheck(_, info) {
      info.restore();
    }
    function constructFactory(onreturn, fields) {
      return hook;
      function hook(constructs2, returnState, bogusState) {
        let listOfConstructs;
        let constructIndex;
        let currentConstruct;
        let info;
        return Array.isArray(constructs2) ? handleListOfConstructs(constructs2) : "tokenize" in constructs2 ? (
          // @ts-expect-error Looks like a construct.
          handleListOfConstructs([constructs2])
        ) : handleMapOfConstructs(constructs2);
        function handleMapOfConstructs(map2) {
          return start;
          function start(code2) {
            const def = code2 !== null && map2[code2];
            const all2 = code2 !== null && map2.null;
            const list2 = [
              // To do: add more extension tests.
              /* c8 ignore next 2 */
              ...Array.isArray(def) ? def : def ? [def] : [],
              ...Array.isArray(all2) ? all2 : all2 ? [all2] : []
            ];
            return handleListOfConstructs(list2)(code2);
          }
        }
        function handleListOfConstructs(list2) {
          listOfConstructs = list2;
          constructIndex = 0;
          if (list2.length === 0) {
            return bogusState;
          }
          return handleConstruct(list2[constructIndex]);
        }
        function handleConstruct(construct) {
          return start;
          function start(code2) {
            info = store();
            currentConstruct = construct;
            if (!construct.partial) {
              context.currentConstruct = construct;
            }
            if (construct.name && context.parser.constructs.disable.null.includes(construct.name)) {
              return nok();
            }
            return construct.tokenize.call(
              // If we do have fields, create an object w/ `context` as its
              // prototype.
              // This allows a “live binding”, which is needed for `interrupt`.
              fields ? Object.assign(Object.create(context), fields) : context,
              effects,
              ok2,
              nok
            )(code2);
          }
        }
        function ok2(code2) {
          onreturn(currentConstruct, info);
          return returnState;
        }
        function nok(code2) {
          info.restore();
          if (++constructIndex < listOfConstructs.length) {
            return handleConstruct(listOfConstructs[constructIndex]);
          }
          return bogusState;
        }
      }
    }
    function addResult(construct, from2) {
      if (construct.resolveAll && !resolveAllConstructs.includes(construct)) {
        resolveAllConstructs.push(construct);
      }
      if (construct.resolve) {
        splice(
          context.events,
          from2,
          context.events.length - from2,
          construct.resolve(context.events.slice(from2), context)
        );
      }
      if (construct.resolveTo) {
        context.events = construct.resolveTo(context.events, context);
      }
    }
    function store() {
      const startPoint = now();
      const startPrevious = context.previous;
      const startCurrentConstruct = context.currentConstruct;
      const startEventsIndex = context.events.length;
      const startStack = Array.from(stack);
      return {
        restore,
        from: startEventsIndex
      };
      function restore() {
        point2 = startPoint;
        context.previous = startPrevious;
        context.currentConstruct = startCurrentConstruct;
        context.events.length = startEventsIndex;
        stack = startStack;
        accountForPotentialSkip();
      }
    }
    function accountForPotentialSkip() {
      if (point2.line in columnStart && point2.column < 2) {
        point2.column = columnStart[point2.line];
        point2.offset += columnStart[point2.line] - 1;
      }
    }
  }
  function sliceChunks(chunks, token) {
    const startIndex = token.start._index;
    const startBufferIndex = token.start._bufferIndex;
    const endIndex = token.end._index;
    const endBufferIndex = token.end._bufferIndex;
    let view;
    if (startIndex === endIndex) {
      view = [chunks[startIndex].slice(startBufferIndex, endBufferIndex)];
    } else {
      view = chunks.slice(startIndex, endIndex);
      if (startBufferIndex > -1) {
        const head = view[0];
        if (typeof head === "string") {
          view[0] = head.slice(startBufferIndex);
        } else {
          view.shift();
        }
      }
      if (endBufferIndex > 0) {
        view.push(chunks[endIndex].slice(0, endBufferIndex));
      }
    }
    return view;
  }
  function serializeChunks(chunks, expandTabs) {
    let index2 = -1;
    const result = [];
    let atTab;
    while (++index2 < chunks.length) {
      const chunk = chunks[index2];
      let value;
      if (typeof chunk === "string") {
        value = chunk;
      } else
        switch (chunk) {
          case -5: {
            value = "\r";
            break;
          }
          case -4: {
            value = "\n";
            break;
          }
          case -3: {
            value = "\r\n";
            break;
          }
          case -2: {
            value = expandTabs ? " " : "	";
            break;
          }
          case -1: {
            if (!expandTabs && atTab) continue;
            value = " ";
            break;
          }
          default: {
            value = String.fromCharCode(chunk);
          }
        }
      atTab = chunk === -2;
      result.push(value);
    }
    return result.join("");
  }
  const document$1 = {
    [42]: list$2,
    [43]: list$2,
    [45]: list$2,
    [48]: list$2,
    [49]: list$2,
    [50]: list$2,
    [51]: list$2,
    [52]: list$2,
    [53]: list$2,
    [54]: list$2,
    [55]: list$2,
    [56]: list$2,
    [57]: list$2,
    [62]: blockQuote
  };
  const contentInitial = {
    [91]: definition$1
  };
  const flowInitial = {
    [-2]: codeIndented,
    [-1]: codeIndented,
    [32]: codeIndented
  };
  const flow = {
    [35]: headingAtx,
    [42]: thematicBreak$2,
    [45]: [setextUnderline, thematicBreak$2],
    [60]: htmlFlow,
    [61]: setextUnderline,
    [95]: thematicBreak$2,
    [96]: codeFenced,
    [126]: codeFenced
  };
  const string = {
    [38]: characterReference,
    [92]: characterEscape
  };
  const text$3 = {
    [-5]: lineEnding,
    [-4]: lineEnding,
    [-3]: lineEnding,
    [33]: labelStartImage,
    [38]: characterReference,
    [42]: attention,
    [60]: [autolink, htmlText],
    [91]: labelStartLink,
    [92]: [hardBreakEscape, characterEscape],
    [93]: labelEnd,
    [95]: attention,
    [96]: codeText
  };
  const insideSpan = {
    null: [attention, resolver]
  };
  const attentionMarkers = {
    null: [42, 95]
  };
  const disable = {
    null: []
  };
  const defaultConstructs = /* @__PURE__ */ Object.freeze(/* @__PURE__ */ Object.defineProperty({
    __proto__: null,
    attentionMarkers,
    contentInitial,
    disable,
    document: document$1,
    flow,
    flowInitial,
    insideSpan,
    string,
    text: text$3
  }, Symbol.toStringTag, { value: "Module" }));
  function parse(options) {
    const settings = options || {};
    const constructs2 = (
      /** @type {FullNormalizedExtension} */
      combineExtensions([defaultConstructs, ...settings.extensions || []])
    );
    const parser = {
      defined: [],
      lazy: {},
      constructs: constructs2,
      content: create2(content$1),
      document: create2(document$2),
      flow: create2(flow$1),
      string: create2(string$1),
      text: create2(text$4)
    };
    return parser;
    function create2(initial) {
      return creator;
      function creator(from) {
        return createTokenizer(parser, initial, from);
      }
    }
  }
  function postprocess(events) {
    while (!subtokenize(events)) {
    }
    return events;
  }
  const search = /[\0\t\n\r]/g;
  function preprocess() {
    let column = 1;
    let buffer = "";
    let start = true;
    let atCarriageReturn;
    return preprocessor;
    function preprocessor(value, encoding, end) {
      const chunks = [];
      let match;
      let next;
      let startPosition;
      let endPosition;
      let code2;
      value = buffer + (typeof value === "string" ? value.toString() : new TextDecoder(encoding || void 0).decode(value));
      startPosition = 0;
      buffer = "";
      if (start) {
        if (value.charCodeAt(0) === 65279) {
          startPosition++;
        }
        start = void 0;
      }
      while (startPosition < value.length) {
        search.lastIndex = startPosition;
        match = search.exec(value);
        endPosition = match && match.index !== void 0 ? match.index : value.length;
        code2 = value.charCodeAt(endPosition);
        if (!match) {
          buffer = value.slice(startPosition);
          break;
        }
        if (code2 === 10 && startPosition === endPosition && atCarriageReturn) {
          chunks.push(-3);
          atCarriageReturn = void 0;
        } else {
          if (atCarriageReturn) {
            chunks.push(-5);
            atCarriageReturn = void 0;
          }
          if (startPosition < endPosition) {
            chunks.push(value.slice(startPosition, endPosition));
            column += endPosition - startPosition;
          }
          switch (code2) {
            case 0: {
              chunks.push(65533);
              column++;
              break;
            }
            case 9: {
              next = Math.ceil(column / 4) * 4;
              chunks.push(-2);
              while (column++ < next) chunks.push(-1);
              break;
            }
            case 10: {
              chunks.push(-4);
              column = 1;
              break;
            }
            default: {
              atCarriageReturn = true;
              column = 1;
            }
          }
        }
        startPosition = endPosition + 1;
      }
      if (end) {
        if (atCarriageReturn) chunks.push(-5);
        if (buffer) chunks.push(buffer);
        chunks.push(null);
      }
      return chunks;
    }
  }
  const characterEscapeOrReference = /\\([!-/:-@[-`{-~])|&(#(?:\d{1,7}|x[\da-f]{1,6})|[\da-z]{1,31});/gi;
  function decodeString(value) {
    return value.replace(characterEscapeOrReference, decode);
  }
  function decode($0, $1, $2) {
    if ($1) {
      return $1;
    }
    const head = $2.charCodeAt(0);
    if (head === 35) {
      const head2 = $2.charCodeAt(1);
      const hex = head2 === 120 || head2 === 88;
      return decodeNumericCharacterReference($2.slice(hex ? 2 : 1), hex ? 16 : 10);
    }
    return decodeNamedCharacterReference($2) || $0;
  }
  const own$2 = {}.hasOwnProperty;
  function fromMarkdown(value, encoding, options) {
    if (encoding && typeof encoding === "object") {
      options = encoding;
      encoding = void 0;
    }
    return compiler(options)(postprocess(parse(options).document().write(preprocess()(value, encoding, true))));
  }
  function compiler(options) {
    const config = {
      transforms: [],
      canContainEols: ["emphasis", "fragment", "heading", "paragraph", "strong"],
      enter: {
        autolink: opener(link2),
        autolinkProtocol: onenterdata,
        autolinkEmail: onenterdata,
        atxHeading: opener(heading2),
        blockQuote: opener(blockQuote2),
        characterEscape: onenterdata,
        characterReference: onenterdata,
        codeFenced: opener(codeFlow),
        codeFencedFenceInfo: buffer,
        codeFencedFenceMeta: buffer,
        codeIndented: opener(codeFlow, buffer),
        codeText: opener(codeText2, buffer),
        codeTextData: onenterdata,
        data: onenterdata,
        codeFlowValue: onenterdata,
        definition: opener(definition2),
        definitionDestinationString: buffer,
        definitionLabelString: buffer,
        definitionTitleString: buffer,
        emphasis: opener(emphasis2),
        hardBreakEscape: opener(hardBreak2),
        hardBreakTrailing: opener(hardBreak2),
        htmlFlow: opener(html2, buffer),
        htmlFlowData: onenterdata,
        htmlText: opener(html2, buffer),
        htmlTextData: onenterdata,
        image: opener(image2),
        label: buffer,
        link: opener(link2),
        listItem: opener(listItem2),
        listItemValue: onenterlistitemvalue,
        listOrdered: opener(list2, onenterlistordered),
        listUnordered: opener(list2),
        paragraph: opener(paragraph2),
        reference: onenterreference,
        referenceString: buffer,
        resourceDestinationString: buffer,
        resourceTitleString: buffer,
        setextHeading: opener(heading2),
        strong: opener(strong2),
        thematicBreak: opener(thematicBreak2)
      },
      exit: {
        atxHeading: closer(),
        atxHeadingSequence: onexitatxheadingsequence,
        autolink: closer(),
        autolinkEmail: onexitautolinkemail,
        autolinkProtocol: onexitautolinkprotocol,
        blockQuote: closer(),
        characterEscapeValue: onexitdata,
        characterReferenceMarkerHexadecimal: onexitcharacterreferencemarker,
        characterReferenceMarkerNumeric: onexitcharacterreferencemarker,
        characterReferenceValue: onexitcharacterreferencevalue,
        characterReference: onexitcharacterreference,
        codeFenced: closer(onexitcodefenced),
        codeFencedFence: onexitcodefencedfence,
        codeFencedFenceInfo: onexitcodefencedfenceinfo,
        codeFencedFenceMeta: onexitcodefencedfencemeta,
        codeFlowValue: onexitdata,
        codeIndented: closer(onexitcodeindented),
        codeText: closer(onexitcodetext),
        codeTextData: onexitdata,
        data: onexitdata,
        definition: closer(),
        definitionDestinationString: onexitdefinitiondestinationstring,
        definitionLabelString: onexitdefinitionlabelstring,
        definitionTitleString: onexitdefinitiontitlestring,
        emphasis: closer(),
        hardBreakEscape: closer(onexithardbreak),
        hardBreakTrailing: closer(onexithardbreak),
        htmlFlow: closer(onexithtmlflow),
        htmlFlowData: onexitdata,
        htmlText: closer(onexithtmltext),
        htmlTextData: onexitdata,
        image: closer(onexitimage),
        label: onexitlabel,
        labelText: onexitlabeltext,
        lineEnding: onexitlineending,
        link: closer(onexitlink),
        listItem: closer(),
        listOrdered: closer(),
        listUnordered: closer(),
        paragraph: closer(),
        referenceString: onexitreferencestring,
        resourceDestinationString: onexitresourcedestinationstring,
        resourceTitleString: onexitresourcetitlestring,
        resource: onexitresource,
        setextHeading: closer(onexitsetextheading),
        setextHeadingLineSequence: onexitsetextheadinglinesequence,
        setextHeadingText: onexitsetextheadingtext,
        strong: closer(),
        thematicBreak: closer()
      }
    };
    configure(config, (options || {}).mdastExtensions || []);
    const data = {};
    return compile;
    function compile(events) {
      let tree = {
        type: "root",
        children: []
      };
      const context = {
        stack: [tree],
        tokenStack: [],
        config,
        enter,
        exit: exit2,
        buffer,
        resume,
        data
      };
      const listStack = [];
      let index2 = -1;
      while (++index2 < events.length) {
        if (events[index2][1].type === "listOrdered" || events[index2][1].type === "listUnordered") {
          if (events[index2][0] === "enter") {
            listStack.push(index2);
          } else {
            const tail = listStack.pop();
            index2 = prepareList(events, tail, index2);
          }
        }
      }
      index2 = -1;
      while (++index2 < events.length) {
        const handler = config[events[index2][0]];
        if (own$2.call(handler, events[index2][1].type)) {
          handler[events[index2][1].type].call(Object.assign({
            sliceSerialize: events[index2][2].sliceSerialize
          }, context), events[index2][1]);
        }
      }
      if (context.tokenStack.length > 0) {
        const tail = context.tokenStack[context.tokenStack.length - 1];
        const handler = tail[1] || defaultOnError;
        handler.call(context, void 0, tail[0]);
      }
      tree.position = {
        start: point(events.length > 0 ? events[0][1].start : {
          line: 1,
          column: 1,
          offset: 0
        }),
        end: point(events.length > 0 ? events[events.length - 2][1].end : {
          line: 1,
          column: 1,
          offset: 0
        })
      };
      index2 = -1;
      while (++index2 < config.transforms.length) {
        tree = config.transforms[index2](tree) || tree;
      }
      return tree;
    }
    function prepareList(events, start, length) {
      let index2 = start - 1;
      let containerBalance = -1;
      let listSpread = false;
      let listItem3;
      let lineIndex;
      let firstBlankLineIndex;
      let atMarker;
      while (++index2 <= length) {
        const event = events[index2];
        switch (event[1].type) {
          case "listUnordered":
          case "listOrdered":
          case "blockQuote": {
            if (event[0] === "enter") {
              containerBalance++;
            } else {
              containerBalance--;
            }
            atMarker = void 0;
            break;
          }
          case "lineEndingBlank": {
            if (event[0] === "enter") {
              if (listItem3 && !atMarker && !containerBalance && !firstBlankLineIndex) {
                firstBlankLineIndex = index2;
              }
              atMarker = void 0;
            }
            break;
          }
          case "linePrefix":
          case "listItemValue":
          case "listItemMarker":
          case "listItemPrefix":
          case "listItemPrefixWhitespace": {
            break;
          }
          default: {
            atMarker = void 0;
          }
        }
        if (!containerBalance && event[0] === "enter" && event[1].type === "listItemPrefix" || containerBalance === -1 && event[0] === "exit" && (event[1].type === "listUnordered" || event[1].type === "listOrdered")) {
          if (listItem3) {
            let tailIndex = index2;
            lineIndex = void 0;
            while (tailIndex--) {
              const tailEvent = events[tailIndex];
              if (tailEvent[1].type === "lineEnding" || tailEvent[1].type === "lineEndingBlank") {
                if (tailEvent[0] === "exit") continue;
                if (lineIndex) {
                  events[lineIndex][1].type = "lineEndingBlank";
                  listSpread = true;
                }
                tailEvent[1].type = "lineEnding";
                lineIndex = tailIndex;
              } else if (tailEvent[1].type === "linePrefix" || tailEvent[1].type === "blockQuotePrefix" || tailEvent[1].type === "blockQuotePrefixWhitespace" || tailEvent[1].type === "blockQuoteMarker" || tailEvent[1].type === "listItemIndent") ;
              else {
                break;
              }
            }
            if (firstBlankLineIndex && (!lineIndex || firstBlankLineIndex < lineIndex)) {
              listItem3._spread = true;
            }
            listItem3.end = Object.assign({}, lineIndex ? events[lineIndex][1].start : event[1].end);
            events.splice(lineIndex || index2, 0, ["exit", listItem3, event[2]]);
            index2++;
            length++;
          }
          if (event[1].type === "listItemPrefix") {
            const item = {
              type: "listItem",
              _spread: false,
              start: Object.assign({}, event[1].start),
              // @ts-expect-error: we’ll add `end` in a second.
              end: void 0
            };
            listItem3 = item;
            events.splice(index2, 0, ["enter", item, event[2]]);
            index2++;
            length++;
            firstBlankLineIndex = void 0;
            atMarker = true;
          }
        }
      }
      events[start][1]._spread = listSpread;
      return length;
    }
    function opener(create2, and) {
      return open;
      function open(token) {
        enter.call(this, create2(token), token);
        if (and) and.call(this, token);
      }
    }
    function buffer() {
      this.stack.push({
        type: "fragment",
        children: []
      });
    }
    function enter(node2, token, errorHandler) {
      const parent = this.stack[this.stack.length - 1];
      const siblings = parent.children;
      siblings.push(node2);
      this.stack.push(node2);
      this.tokenStack.push([token, errorHandler || void 0]);
      node2.position = {
        start: point(token.start),
        // @ts-expect-error: `end` will be patched later.
        end: void 0
      };
    }
    function closer(and) {
      return close;
      function close(token) {
        if (and) and.call(this, token);
        exit2.call(this, token);
      }
    }
    function exit2(token, onExitError) {
      const node2 = this.stack.pop();
      const open = this.tokenStack.pop();
      if (!open) {
        throw new Error("Cannot close `" + token.type + "` (" + stringifyPosition({
          start: token.start,
          end: token.end
        }) + "): it’s not open");
      } else if (open[0].type !== token.type) {
        if (onExitError) {
          onExitError.call(this, token, open[0]);
        } else {
          const handler = open[1] || defaultOnError;
          handler.call(this, token, open[0]);
        }
      }
      node2.position.end = point(token.end);
    }
    function resume() {
      return toString$1(this.stack.pop());
    }
    function onenterlistordered() {
      this.data.expectingFirstListItemValue = true;
    }
    function onenterlistitemvalue(token) {
      if (this.data.expectingFirstListItemValue) {
        const ancestor = this.stack[this.stack.length - 2];
        ancestor.start = Number.parseInt(this.sliceSerialize(token), 10);
        this.data.expectingFirstListItemValue = void 0;
      }
    }
    function onexitcodefencedfenceinfo() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.lang = data2;
    }
    function onexitcodefencedfencemeta() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.meta = data2;
    }
    function onexitcodefencedfence() {
      if (this.data.flowCodeInside) return;
      this.buffer();
      this.data.flowCodeInside = true;
    }
    function onexitcodefenced() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.value = data2.replace(/^(\r?\n|\r)|(\r?\n|\r)$/g, "");
      this.data.flowCodeInside = void 0;
    }
    function onexitcodeindented() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.value = data2.replace(/(\r?\n|\r)$/g, "");
    }
    function onexitdefinitionlabelstring(token) {
      const label = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.label = label;
      node2.identifier = normalizeIdentifier(this.sliceSerialize(token)).toLowerCase();
    }
    function onexitdefinitiontitlestring() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.title = data2;
    }
    function onexitdefinitiondestinationstring() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.url = data2;
    }
    function onexitatxheadingsequence(token) {
      const node2 = this.stack[this.stack.length - 1];
      if (!node2.depth) {
        const depth = this.sliceSerialize(token).length;
        node2.depth = depth;
      }
    }
    function onexitsetextheadingtext() {
      this.data.setextHeadingSlurpLineEnding = true;
    }
    function onexitsetextheadinglinesequence(token) {
      const node2 = this.stack[this.stack.length - 1];
      node2.depth = this.sliceSerialize(token).codePointAt(0) === 61 ? 1 : 2;
    }
    function onexitsetextheading() {
      this.data.setextHeadingSlurpLineEnding = void 0;
    }
    function onenterdata(token) {
      const node2 = this.stack[this.stack.length - 1];
      const siblings = node2.children;
      let tail = siblings[siblings.length - 1];
      if (!tail || tail.type !== "text") {
        tail = text2();
        tail.position = {
          start: point(token.start),
          // @ts-expect-error: we’ll add `end` later.
          end: void 0
        };
        siblings.push(tail);
      }
      this.stack.push(tail);
    }
    function onexitdata(token) {
      const tail = this.stack.pop();
      tail.value += this.sliceSerialize(token);
      tail.position.end = point(token.end);
    }
    function onexitlineending(token) {
      const context = this.stack[this.stack.length - 1];
      if (this.data.atHardBreak) {
        const tail = context.children[context.children.length - 1];
        tail.position.end = point(token.end);
        this.data.atHardBreak = void 0;
        return;
      }
      if (!this.data.setextHeadingSlurpLineEnding && config.canContainEols.includes(context.type)) {
        onenterdata.call(this, token);
        onexitdata.call(this, token);
      }
    }
    function onexithardbreak() {
      this.data.atHardBreak = true;
    }
    function onexithtmlflow() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.value = data2;
    }
    function onexithtmltext() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.value = data2;
    }
    function onexitcodetext() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.value = data2;
    }
    function onexitlink() {
      const node2 = this.stack[this.stack.length - 1];
      if (this.data.inReference) {
        const referenceType = this.data.referenceType || "shortcut";
        node2.type += "Reference";
        node2.referenceType = referenceType;
        delete node2.url;
        delete node2.title;
      } else {
        delete node2.identifier;
        delete node2.label;
      }
      this.data.referenceType = void 0;
    }
    function onexitimage() {
      const node2 = this.stack[this.stack.length - 1];
      if (this.data.inReference) {
        const referenceType = this.data.referenceType || "shortcut";
        node2.type += "Reference";
        node2.referenceType = referenceType;
        delete node2.url;
        delete node2.title;
      } else {
        delete node2.identifier;
        delete node2.label;
      }
      this.data.referenceType = void 0;
    }
    function onexitlabeltext(token) {
      const string2 = this.sliceSerialize(token);
      const ancestor = this.stack[this.stack.length - 2];
      ancestor.label = decodeString(string2);
      ancestor.identifier = normalizeIdentifier(string2).toLowerCase();
    }
    function onexitlabel() {
      const fragment = this.stack[this.stack.length - 1];
      const value = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      this.data.inReference = true;
      if (node2.type === "link") {
        const children = fragment.children;
        node2.children = children;
      } else {
        node2.alt = value;
      }
    }
    function onexitresourcedestinationstring() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.url = data2;
    }
    function onexitresourcetitlestring() {
      const data2 = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.title = data2;
    }
    function onexitresource() {
      this.data.inReference = void 0;
    }
    function onenterreference() {
      this.data.referenceType = "collapsed";
    }
    function onexitreferencestring(token) {
      const label = this.resume();
      const node2 = this.stack[this.stack.length - 1];
      node2.label = label;
      node2.identifier = normalizeIdentifier(this.sliceSerialize(token)).toLowerCase();
      this.data.referenceType = "full";
    }
    function onexitcharacterreferencemarker(token) {
      this.data.characterReferenceType = token.type;
    }
    function onexitcharacterreferencevalue(token) {
      const data2 = this.sliceSerialize(token);
      const type = this.data.characterReferenceType;
      let value;
      if (type) {
        value = decodeNumericCharacterReference(data2, type === "characterReferenceMarkerNumeric" ? 10 : 16);
        this.data.characterReferenceType = void 0;
      } else {
        const result = decodeNamedCharacterReference(data2);
        value = result;
      }
      const tail = this.stack[this.stack.length - 1];
      tail.value += value;
    }
    function onexitcharacterreference(token) {
      const tail = this.stack.pop();
      tail.position.end = point(token.end);
    }
    function onexitautolinkprotocol(token) {
      onexitdata.call(this, token);
      const node2 = this.stack[this.stack.length - 1];
      node2.url = this.sliceSerialize(token);
    }
    function onexitautolinkemail(token) {
      onexitdata.call(this, token);
      const node2 = this.stack[this.stack.length - 1];
      node2.url = "mailto:" + this.sliceSerialize(token);
    }
    function blockQuote2() {
      return {
        type: "blockquote",
        children: []
      };
    }
    function codeFlow() {
      return {
        type: "code",
        lang: null,
        meta: null,
        value: ""
      };
    }
    function codeText2() {
      return {
        type: "inlineCode",
        value: ""
      };
    }
    function definition2() {
      return {
        type: "definition",
        identifier: "",
        label: null,
        title: null,
        url: ""
      };
    }
    function emphasis2() {
      return {
        type: "emphasis",
        children: []
      };
    }
    function heading2() {
      return {
        type: "heading",
        // @ts-expect-error `depth` will be set later.
        depth: 0,
        children: []
      };
    }
    function hardBreak2() {
      return {
        type: "break"
      };
    }
    function html2() {
      return {
        type: "html",
        value: ""
      };
    }
    function image2() {
      return {
        type: "image",
        title: null,
        url: "",
        alt: null
      };
    }
    function link2() {
      return {
        type: "link",
        title: null,
        url: "",
        children: []
      };
    }
    function list2(token) {
      return {
        type: "list",
        ordered: token.type === "listOrdered",
        start: null,
        spread: token._spread,
        children: []
      };
    }
    function listItem2(token) {
      return {
        type: "listItem",
        spread: token._spread,
        checked: null,
        children: []
      };
    }
    function paragraph2() {
      return {
        type: "paragraph",
        children: []
      };
    }
    function strong2() {
      return {
        type: "strong",
        children: []
      };
    }
    function text2() {
      return {
        type: "text",
        value: ""
      };
    }
    function thematicBreak2() {
      return {
        type: "thematicBreak"
      };
    }
  }
  function point(d) {
    return {
      line: d.line,
      column: d.column,
      offset: d.offset
    };
  }
  function configure(combined, extensions) {
    let index2 = -1;
    while (++index2 < extensions.length) {
      const value = extensions[index2];
      if (Array.isArray(value)) {
        configure(combined, value);
      } else {
        extension(combined, value);
      }
    }
  }
  function extension(combined, extension2) {
    let key;
    for (key in extension2) {
      if (own$2.call(extension2, key)) {
        switch (key) {
          case "canContainEols": {
            const right = extension2[key];
            if (right) {
              combined[key].push(...right);
            }
            break;
          }
          case "transforms": {
            const right = extension2[key];
            if (right) {
              combined[key].push(...right);
            }
            break;
          }
          case "enter":
          case "exit": {
            const right = extension2[key];
            if (right) {
              Object.assign(combined[key], right);
            }
            break;
          }
        }
      }
    }
  }
  function defaultOnError(left, right) {
    if (left) {
      throw new Error("Cannot close `" + left.type + "` (" + stringifyPosition({
        start: left.start,
        end: left.end
      }) + "): a different token (`" + right.type + "`, " + stringifyPosition({
        start: right.start,
        end: right.end
      }) + ") is open");
    } else {
      throw new Error("Cannot close document, a token (`" + right.type + "`, " + stringifyPosition({
        start: right.start,
        end: right.end
      }) + ") is still open");
    }
  }
  function remarkParse(options) {
    const self2 = this;
    self2.parser = parser;
    function parser(doc) {
      return fromMarkdown(doc, {
        ...self2.data("settings"),
        ...options,
        // Note: these options are not in the readme.
        // The goal is for them to be set by plugins on `data` instead of being
        // passed by users.
        extensions: self2.data("micromarkExtensions") || [],
        mdastExtensions: self2.data("fromMarkdownExtensions") || []
      });
    }
  }
  function blockquote$1(state, node2) {
    const result = {
      type: "element",
      tagName: "blockquote",
      properties: {},
      children: state.wrap(state.all(node2), true)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function hardBreak$1(state, node2) {
    const result = { type: "element", tagName: "br", properties: {}, children: [] };
    state.patch(node2, result);
    return [state.applyData(node2, result), { type: "text", value: "\n" }];
  }
  function code$2(state, node2) {
    const value = node2.value ? node2.value + "\n" : "";
    const properties = {};
    const language = node2.lang ? node2.lang.split(/\s+/) : [];
    if (language.length > 0) {
      properties.className = ["language-" + language[0]];
    }
    let result = {
      type: "element",
      tagName: "code",
      properties,
      children: [{ type: "text", value }]
    };
    if (node2.meta) {
      result.data = { meta: node2.meta };
    }
    state.patch(node2, result);
    result = state.applyData(node2, result);
    result = { type: "element", tagName: "pre", properties: {}, children: [result] };
    state.patch(node2, result);
    return result;
  }
  function strikethrough(state, node2) {
    const result = {
      type: "element",
      tagName: "del",
      properties: {},
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function emphasis$1(state, node2) {
    const result = {
      type: "element",
      tagName: "em",
      properties: {},
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function footnoteReference$1(state, node2) {
    const clobberPrefix = typeof state.options.clobberPrefix === "string" ? state.options.clobberPrefix : "user-content-";
    const id = String(node2.identifier).toUpperCase();
    const safeId = normalizeUri(id.toLowerCase());
    const index2 = state.footnoteOrder.indexOf(id);
    let counter;
    let reuseCounter = state.footnoteCounts.get(id);
    if (reuseCounter === void 0) {
      reuseCounter = 0;
      state.footnoteOrder.push(id);
      counter = state.footnoteOrder.length;
    } else {
      counter = index2 + 1;
    }
    reuseCounter += 1;
    state.footnoteCounts.set(id, reuseCounter);
    const link2 = {
      type: "element",
      tagName: "a",
      properties: {
        href: "#" + clobberPrefix + "fn-" + safeId,
        id: clobberPrefix + "fnref-" + safeId + (reuseCounter > 1 ? "-" + reuseCounter : ""),
        dataFootnoteRef: true,
        ariaDescribedBy: ["footnote-label"]
      },
      children: [{ type: "text", value: String(counter) }]
    };
    state.patch(node2, link2);
    const sup = {
      type: "element",
      tagName: "sup",
      properties: {},
      children: [link2]
    };
    state.patch(node2, sup);
    return state.applyData(node2, sup);
  }
  function heading$1(state, node2) {
    const result = {
      type: "element",
      tagName: "h" + node2.depth,
      properties: {},
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function html$1(state, node2) {
    if (state.options.allowDangerousHtml) {
      const result = { type: "raw", value: node2.value };
      state.patch(node2, result);
      return state.applyData(node2, result);
    }
    return void 0;
  }
  function revert(state, node2) {
    const subtype = node2.referenceType;
    let suffix = "]";
    if (subtype === "collapsed") {
      suffix += "[]";
    } else if (subtype === "full") {
      suffix += "[" + (node2.label || node2.identifier) + "]";
    }
    if (node2.type === "imageReference") {
      return [{ type: "text", value: "![" + node2.alt + suffix }];
    }
    const contents = state.all(node2);
    const head = contents[0];
    if (head && head.type === "text") {
      head.value = "[" + head.value;
    } else {
      contents.unshift({ type: "text", value: "[" });
    }
    const tail = contents[contents.length - 1];
    if (tail && tail.type === "text") {
      tail.value += suffix;
    } else {
      contents.push({ type: "text", value: suffix });
    }
    return contents;
  }
  function imageReference$1(state, node2) {
    const id = String(node2.identifier).toUpperCase();
    const definition2 = state.definitionById.get(id);
    if (!definition2) {
      return revert(state, node2);
    }
    const properties = { src: normalizeUri(definition2.url || ""), alt: node2.alt };
    if (definition2.title !== null && definition2.title !== void 0) {
      properties.title = definition2.title;
    }
    const result = { type: "element", tagName: "img", properties, children: [] };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function image$1(state, node2) {
    const properties = { src: normalizeUri(node2.url) };
    if (node2.alt !== null && node2.alt !== void 0) {
      properties.alt = node2.alt;
    }
    if (node2.title !== null && node2.title !== void 0) {
      properties.title = node2.title;
    }
    const result = { type: "element", tagName: "img", properties, children: [] };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function inlineCode$1(state, node2) {
    const text2 = { type: "text", value: node2.value.replace(/\r?\n|\r/g, " ") };
    state.patch(node2, text2);
    const result = {
      type: "element",
      tagName: "code",
      properties: {},
      children: [text2]
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function linkReference$1(state, node2) {
    const id = String(node2.identifier).toUpperCase();
    const definition2 = state.definitionById.get(id);
    if (!definition2) {
      return revert(state, node2);
    }
    const properties = { href: normalizeUri(definition2.url || "") };
    if (definition2.title !== null && definition2.title !== void 0) {
      properties.title = definition2.title;
    }
    const result = {
      type: "element",
      tagName: "a",
      properties,
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function link$1(state, node2) {
    const properties = { href: normalizeUri(node2.url) };
    if (node2.title !== null && node2.title !== void 0) {
      properties.title = node2.title;
    }
    const result = {
      type: "element",
      tagName: "a",
      properties,
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function listItem$1(state, node2, parent) {
    const results = state.all(node2);
    const loose = parent ? listLoose(parent) : listItemLoose(node2);
    const properties = {};
    const children = [];
    if (typeof node2.checked === "boolean") {
      const head = results[0];
      let paragraph2;
      if (head && head.type === "element" && head.tagName === "p") {
        paragraph2 = head;
      } else {
        paragraph2 = { type: "element", tagName: "p", properties: {}, children: [] };
        results.unshift(paragraph2);
      }
      if (paragraph2.children.length > 0) {
        paragraph2.children.unshift({ type: "text", value: " " });
      }
      paragraph2.children.unshift({
        type: "element",
        tagName: "input",
        properties: { type: "checkbox", checked: node2.checked, disabled: true },
        children: []
      });
      properties.className = ["task-list-item"];
    }
    let index2 = -1;
    while (++index2 < results.length) {
      const child = results[index2];
      if (loose || index2 !== 0 || child.type !== "element" || child.tagName !== "p") {
        children.push({ type: "text", value: "\n" });
      }
      if (child.type === "element" && child.tagName === "p" && !loose) {
        children.push(...child.children);
      } else {
        children.push(child);
      }
    }
    const tail = results[results.length - 1];
    if (tail && (loose || tail.type !== "element" || tail.tagName !== "p")) {
      children.push({ type: "text", value: "\n" });
    }
    const result = { type: "element", tagName: "li", properties, children };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function listLoose(node2) {
    let loose = false;
    if (node2.type === "list") {
      loose = node2.spread || false;
      const children = node2.children;
      let index2 = -1;
      while (!loose && ++index2 < children.length) {
        loose = listItemLoose(children[index2]);
      }
    }
    return loose;
  }
  function listItemLoose(node2) {
    const spread = node2.spread;
    return spread === null || spread === void 0 ? node2.children.length > 1 : spread;
  }
  function list$1(state, node2) {
    const properties = {};
    const results = state.all(node2);
    let index2 = -1;
    if (typeof node2.start === "number" && node2.start !== 1) {
      properties.start = node2.start;
    }
    while (++index2 < results.length) {
      const child = results[index2];
      if (child.type === "element" && child.tagName === "li" && child.properties && Array.isArray(child.properties.className) && child.properties.className.includes("task-list-item")) {
        properties.className = ["contains-task-list"];
        break;
      }
    }
    const result = {
      type: "element",
      tagName: node2.ordered ? "ol" : "ul",
      properties,
      children: state.wrap(results, true)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function paragraph$1(state, node2) {
    const result = {
      type: "element",
      tagName: "p",
      properties: {},
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function root$1(state, node2) {
    const result = { type: "root", children: state.wrap(state.all(node2)) };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function strong$1(state, node2) {
    const result = {
      type: "element",
      tagName: "strong",
      properties: {},
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function table(state, node2) {
    const rows = state.all(node2);
    const firstRow = rows.shift();
    const tableContent = [];
    if (firstRow) {
      const head = {
        type: "element",
        tagName: "thead",
        properties: {},
        children: state.wrap([firstRow], true)
      };
      state.patch(node2.children[0], head);
      tableContent.push(head);
    }
    if (rows.length > 0) {
      const body = {
        type: "element",
        tagName: "tbody",
        properties: {},
        children: state.wrap(rows, true)
      };
      const start = pointStart(node2.children[1]);
      const end = pointEnd(node2.children[node2.children.length - 1]);
      if (start && end) body.position = { start, end };
      tableContent.push(body);
    }
    const result = {
      type: "element",
      tagName: "table",
      properties: {},
      children: state.wrap(tableContent, true)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function tableRow(state, node2, parent) {
    const siblings = parent ? parent.children : void 0;
    const rowIndex = siblings ? siblings.indexOf(node2) : 1;
    const tagName = rowIndex === 0 ? "th" : "td";
    const align = parent && parent.type === "table" ? parent.align : void 0;
    const length = align ? align.length : node2.children.length;
    let cellIndex = -1;
    const cells = [];
    while (++cellIndex < length) {
      const cell = node2.children[cellIndex];
      const properties = {};
      const alignValue = align ? align[cellIndex] : void 0;
      if (alignValue) {
        properties.align = alignValue;
      }
      let result2 = { type: "element", tagName, properties, children: [] };
      if (cell) {
        result2.children = state.all(cell);
        state.patch(cell, result2);
        result2 = state.applyData(cell, result2);
      }
      cells.push(result2);
    }
    const result = {
      type: "element",
      tagName: "tr",
      properties: {},
      children: state.wrap(cells, true)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function tableCell(state, node2) {
    const result = {
      type: "element",
      tagName: "td",
      // Assume body cell.
      properties: {},
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  const tab = 9;
  const space = 32;
  function trimLines(value) {
    const source = String(value);
    const search2 = /\r?\n|\r/g;
    let match = search2.exec(source);
    let last = 0;
    const lines = [];
    while (match) {
      lines.push(
        trimLine(source.slice(last, match.index), last > 0, true),
        match[0]
      );
      last = match.index + match[0].length;
      match = search2.exec(source);
    }
    lines.push(trimLine(source.slice(last), last > 0, false));
    return lines.join("");
  }
  function trimLine(value, start, end) {
    let startIndex = 0;
    let endIndex = value.length;
    if (start) {
      let code2 = value.codePointAt(startIndex);
      while (code2 === tab || code2 === space) {
        startIndex++;
        code2 = value.codePointAt(startIndex);
      }
    }
    if (end) {
      let code2 = value.codePointAt(endIndex - 1);
      while (code2 === tab || code2 === space) {
        endIndex--;
        code2 = value.codePointAt(endIndex - 1);
      }
    }
    return endIndex > startIndex ? value.slice(startIndex, endIndex) : "";
  }
  function text$2(state, node2) {
    const result = { type: "text", value: trimLines(String(node2.value)) };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function thematicBreak$1(state, node2) {
    const result = {
      type: "element",
      tagName: "hr",
      properties: {},
      children: []
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  const handlers = {
    blockquote: blockquote$1,
    break: hardBreak$1,
    code: code$2,
    delete: strikethrough,
    emphasis: emphasis$1,
    footnoteReference: footnoteReference$1,
    heading: heading$1,
    html: html$1,
    imageReference: imageReference$1,
    image: image$1,
    inlineCode: inlineCode$1,
    linkReference: linkReference$1,
    link: link$1,
    listItem: listItem$1,
    list: list$1,
    paragraph: paragraph$1,
    // @ts-expect-error: root is different, but hard to type.
    root: root$1,
    strong: strong$1,
    table,
    tableCell,
    tableRow,
    text: text$2,
    thematicBreak: thematicBreak$1,
    toml: ignore,
    yaml: ignore,
    definition: ignore,
    footnoteDefinition: ignore
  };
  function ignore() {
    return void 0;
  }
  const VOID = -1;
  const PRIMITIVE = 0;
  const ARRAY = 1;
  const OBJECT = 2;
  const DATE = 3;
  const REGEXP = 4;
  const MAP = 5;
  const SET = 6;
  const ERROR = 7;
  const BIGINT = 8;
  const env = typeof self === "object" ? self : globalThis;
  const guard = (name2, init) => {
    switch (name2) {
      case "Function":
      case "SharedWorker":
      case "Worker":
      case "eval":
      case "setInterval":
      case "setTimeout":
        throw new TypeError("unable to deserialize " + name2);
    }
    return new env[name2](init);
  };
  const deserializer = ($, _) => {
    const as = (out, index2) => {
      $.set(index2, out);
      return out;
    };
    const unpair = (index2) => {
      if ($.has(index2))
        return $.get(index2);
      const [type, value] = _[index2];
      switch (type) {
        case PRIMITIVE:
        case VOID:
          return as(value, index2);
        case ARRAY: {
          const arr = as([], index2);
          for (const index3 of value)
            arr.push(unpair(index3));
          return arr;
        }
        case OBJECT: {
          const object = as({}, index2);
          for (const [key, index3] of value)
            object[unpair(key)] = unpair(index3);
          return object;
        }
        case DATE:
          return as(new Date(value), index2);
        case REGEXP: {
          const { source, flags } = value;
          return as(new RegExp(source, flags), index2);
        }
        case MAP: {
          const map2 = as(/* @__PURE__ */ new Map(), index2);
          for (const [key, index3] of value)
            map2.set(unpair(key), unpair(index3));
          return map2;
        }
        case SET: {
          const set = as(/* @__PURE__ */ new Set(), index2);
          for (const index3 of value)
            set.add(unpair(index3));
          return set;
        }
        case ERROR: {
          const { name: name2, message } = value;
          return as(guard(name2, message), index2);
        }
        case BIGINT:
          return as(BigInt(value), index2);
        case "BigInt":
          return as(Object(BigInt(value)), index2);
        case "ArrayBuffer":
          return as(new Uint8Array(value).buffer, value);
        case "DataView": {
          const { buffer } = new Uint8Array(value);
          return as(new DataView(buffer), value);
        }
      }
      return as(guard(type, value), index2);
    };
    return unpair;
  };
  const deserialize = (serialized) => deserializer(/* @__PURE__ */ new Map(), serialized)(0);
  const EMPTY = "";
  const { toString } = {};
  const { keys } = Object;
  const typeOf = (value) => {
    const type = typeof value;
    if (type !== "object" || !value)
      return [PRIMITIVE, type];
    const asString = toString.call(value).slice(8, -1);
    switch (asString) {
      case "Array":
        return [ARRAY, EMPTY];
      case "Object":
        return [OBJECT, EMPTY];
      case "Date":
        return [DATE, EMPTY];
      case "RegExp":
        return [REGEXP, EMPTY];
      case "Map":
        return [MAP, EMPTY];
      case "Set":
        return [SET, EMPTY];
      case "DataView":
        return [ARRAY, asString];
    }
    if (asString.includes("Array"))
      return [ARRAY, asString];
    if (asString.includes("Error"))
      return [ERROR, asString];
    return [OBJECT, asString];
  };
  const shouldSkip = ([TYPE, type]) => TYPE === PRIMITIVE && (type === "function" || type === "symbol");
  const serializer = (strict, json, $, _) => {
    const as = (out, value) => {
      const index2 = _.push(out) - 1;
      $.set(value, index2);
      return index2;
    };
    const pair = (value) => {
      if ($.has(value))
        return $.get(value);
      let [TYPE, type] = typeOf(value);
      switch (TYPE) {
        case PRIMITIVE: {
          let entry = value;
          switch (type) {
            case "bigint":
              TYPE = BIGINT;
              entry = value.toString();
              break;
            case "function":
            case "symbol":
              if (strict)
                throw new TypeError("unable to serialize " + type);
              entry = null;
              break;
            case "undefined":
              return as([VOID], value);
          }
          return as([TYPE, entry], value);
        }
        case ARRAY: {
          if (type) {
            let spread = value;
            if (type === "DataView") {
              spread = new Uint8Array(value.buffer);
            } else if (type === "ArrayBuffer") {
              spread = new Uint8Array(value);
            }
            return as([type, [...spread]], value);
          }
          const arr = [];
          const index2 = as([TYPE, arr], value);
          for (const entry of value)
            arr.push(pair(entry));
          return index2;
        }
        case OBJECT: {
          if (type) {
            switch (type) {
              case "BigInt":
                return as([type, value.toString()], value);
              case "Boolean":
              case "Number":
              case "String":
                return as([type, value.valueOf()], value);
            }
          }
          if (json && "toJSON" in value)
            return pair(value.toJSON());
          const entries = [];
          const index2 = as([TYPE, entries], value);
          for (const key of keys(value)) {
            if (strict || !shouldSkip(typeOf(value[key])))
              entries.push([pair(key), pair(value[key])]);
          }
          return index2;
        }
        case DATE:
          return as([TYPE, isNaN(value.getTime()) ? EMPTY : value.toISOString()], value);
        case REGEXP: {
          const { source, flags } = value;
          return as([TYPE, { source, flags }], value);
        }
        case MAP: {
          const entries = [];
          const index2 = as([TYPE, entries], value);
          for (const [key, entry] of value) {
            if (strict || !(shouldSkip(typeOf(key)) || shouldSkip(typeOf(entry))))
              entries.push([pair(key), pair(entry)]);
          }
          return index2;
        }
        case SET: {
          const entries = [];
          const index2 = as([TYPE, entries], value);
          for (const entry of value) {
            if (strict || !shouldSkip(typeOf(entry)))
              entries.push(pair(entry));
          }
          return index2;
        }
      }
      const { message } = value;
      return as([TYPE, { name: type, message }], value);
    };
    return pair;
  };
  const serialize$1 = (value, { json, lossy } = {}) => {
    const _ = [];
    return serializer(!(json || lossy), !!json, /* @__PURE__ */ new Map(), _)(value), _;
  };
  const structuredClone$1 = typeof structuredClone === "function" ? (
    /* c8 ignore start */
    (any, options) => options && ("json" in options || "lossy" in options) ? deserialize(serialize$1(any, options)) : structuredClone(any)
  ) : (any, options) => deserialize(serialize$1(any, options));
  function defaultFootnoteBackContent(_, rereferenceIndex) {
    const result = [{ type: "text", value: "↩" }];
    if (rereferenceIndex > 1) {
      result.push({
        type: "element",
        tagName: "sup",
        properties: {},
        children: [{ type: "text", value: String(rereferenceIndex) }]
      });
    }
    return result;
  }
  function defaultFootnoteBackLabel(referenceIndex, rereferenceIndex) {
    return "Back to reference " + (referenceIndex + 1) + (rereferenceIndex > 1 ? "-" + rereferenceIndex : "");
  }
  function footer(state) {
    const clobberPrefix = typeof state.options.clobberPrefix === "string" ? state.options.clobberPrefix : "user-content-";
    const footnoteBackContent = state.options.footnoteBackContent || defaultFootnoteBackContent;
    const footnoteBackLabel = state.options.footnoteBackLabel || defaultFootnoteBackLabel;
    const footnoteLabel = state.options.footnoteLabel || "Footnotes";
    const footnoteLabelTagName = state.options.footnoteLabelTagName || "h2";
    const footnoteLabelProperties = state.options.footnoteLabelProperties || {
      className: ["sr-only"]
    };
    const listItems = [];
    let referenceIndex = -1;
    while (++referenceIndex < state.footnoteOrder.length) {
      const definition2 = state.footnoteById.get(
        state.footnoteOrder[referenceIndex]
      );
      if (!definition2) {
        continue;
      }
      const content2 = state.all(definition2);
      const id = String(definition2.identifier).toUpperCase();
      const safeId = normalizeUri(id.toLowerCase());
      let rereferenceIndex = 0;
      const backReferences = [];
      const counts = state.footnoteCounts.get(id);
      while (counts !== void 0 && ++rereferenceIndex <= counts) {
        if (backReferences.length > 0) {
          backReferences.push({ type: "text", value: " " });
        }
        let children = typeof footnoteBackContent === "string" ? footnoteBackContent : footnoteBackContent(referenceIndex, rereferenceIndex);
        if (typeof children === "string") {
          children = { type: "text", value: children };
        }
        backReferences.push({
          type: "element",
          tagName: "a",
          properties: {
            href: "#" + clobberPrefix + "fnref-" + safeId + (rereferenceIndex > 1 ? "-" + rereferenceIndex : ""),
            dataFootnoteBackref: "",
            ariaLabel: typeof footnoteBackLabel === "string" ? footnoteBackLabel : footnoteBackLabel(referenceIndex, rereferenceIndex),
            className: ["data-footnote-backref"]
          },
          children: Array.isArray(children) ? children : [children]
        });
      }
      const tail = content2[content2.length - 1];
      if (tail && tail.type === "element" && tail.tagName === "p") {
        const tailTail = tail.children[tail.children.length - 1];
        if (tailTail && tailTail.type === "text") {
          tailTail.value += " ";
        } else {
          tail.children.push({ type: "text", value: " " });
        }
        tail.children.push(...backReferences);
      } else {
        content2.push(...backReferences);
      }
      const listItem2 = {
        type: "element",
        tagName: "li",
        properties: { id: clobberPrefix + "fn-" + safeId },
        children: state.wrap(content2, true)
      };
      state.patch(definition2, listItem2);
      listItems.push(listItem2);
    }
    if (listItems.length === 0) {
      return;
    }
    return {
      type: "element",
      tagName: "section",
      properties: { dataFootnotes: true, className: ["footnotes"] },
      children: [
        {
          type: "element",
          tagName: footnoteLabelTagName,
          properties: {
            ...structuredClone$1(footnoteLabelProperties),
            id: "footnote-label"
          },
          children: [{ type: "text", value: footnoteLabel }]
        },
        { type: "text", value: "\n" },
        {
          type: "element",
          tagName: "ol",
          properties: {},
          children: state.wrap(listItems, true)
        },
        { type: "text", value: "\n" }
      ]
    };
  }
  const convert = (
    // Note: overloads in JSDoc can’t yet use different `@template`s.
    /**
     * @type {(
     *   (<Condition extends string>(test: Condition) => (node: unknown, index?: number | null | undefined, parent?: Parent | null | undefined, context?: unknown) => node is Node & {type: Condition}) &
     *   (<Condition extends Props>(test: Condition) => (node: unknown, index?: number | null | undefined, parent?: Parent | null | undefined, context?: unknown) => node is Node & Condition) &
     *   (<Condition extends TestFunction>(test: Condition) => (node: unknown, index?: number | null | undefined, parent?: Parent | null | undefined, context?: unknown) => node is Node & Predicate<Condition, Node>) &
     *   ((test?: null | undefined) => (node?: unknown, index?: number | null | undefined, parent?: Parent | null | undefined, context?: unknown) => node is Node) &
     *   ((test?: Test) => Check)
     * )}
     */
    /**
     * @param {Test} [test]
     * @returns {Check}
     */
    function(test) {
      if (test === null || test === void 0) {
        return ok;
      }
      if (typeof test === "function") {
        return castFactory(test);
      }
      if (typeof test === "object") {
        return Array.isArray(test) ? anyFactory(test) : (
          // Cast because `ReadonlyArray` goes into the above but `isArray`
          // narrows to `Array`.
          propertiesFactory(
            /** @type {Props} */
            test
          )
        );
      }
      if (typeof test === "string") {
        return typeFactory(test);
      }
      throw new Error("Expected function, string, or object as test");
    }
  );
  function anyFactory(tests) {
    const checks2 = [];
    let index2 = -1;
    while (++index2 < tests.length) {
      checks2[index2] = convert(tests[index2]);
    }
    return castFactory(any);
    function any(...parameters) {
      let index3 = -1;
      while (++index3 < checks2.length) {
        if (checks2[index3].apply(this, parameters)) return true;
      }
      return false;
    }
  }
  function propertiesFactory(check) {
    const checkAsRecord = (
      /** @type {Record<string, unknown>} */
      check
    );
    return castFactory(all2);
    function all2(node2) {
      const nodeAsRecord = (
        /** @type {Record<string, unknown>} */
        /** @type {unknown} */
        node2
      );
      let key;
      for (key in check) {
        if (nodeAsRecord[key] !== checkAsRecord[key]) return false;
      }
      return true;
    }
  }
  function typeFactory(check) {
    return castFactory(type);
    function type(node2) {
      return node2 && node2.type === check;
    }
  }
  function castFactory(testFunction) {
    return check;
    function check(value, index2, parent) {
      return Boolean(
        looksLikeANode(value) && testFunction.call(
          this,
          value,
          typeof index2 === "number" ? index2 : void 0,
          parent || void 0
        )
      );
    }
  }
  function ok() {
    return true;
  }
  function looksLikeANode(value) {
    return value !== null && typeof value === "object" && "type" in value;
  }
  function color(d) {
    return d;
  }
  const empty = [];
  const CONTINUE = true;
  const EXIT = false;
  const SKIP = "skip";
  function visitParents(tree, test, visitor, reverse) {
    let check;
    if (typeof test === "function" && typeof visitor !== "function") {
      reverse = visitor;
      visitor = test;
    } else {
      check = test;
    }
    const is = convert(check);
    const step = reverse ? -1 : 1;
    factory(tree, void 0, [])();
    function factory(node2, index2, parents) {
      const value = (
        /** @type {Record<string, unknown>} */
        node2 && typeof node2 === "object" ? node2 : {}
      );
      if (typeof value.type === "string") {
        const name2 = (
          // `hast`
          typeof value.tagName === "string" ? value.tagName : (
            // `xast`
            typeof value.name === "string" ? value.name : void 0
          )
        );
        Object.defineProperty(visit2, "name", {
          value: "node (" + color(node2.type + (name2 ? "<" + name2 + ">" : "")) + ")"
        });
      }
      return visit2;
      function visit2() {
        let result = empty;
        let subresult;
        let offset;
        let grandparents;
        if (!test || is(node2, index2, parents[parents.length - 1] || void 0)) {
          result = toResult(visitor(node2, parents));
          if (result[0] === EXIT) {
            return result;
          }
        }
        if ("children" in node2 && node2.children) {
          const nodeAsParent = (
            /** @type {UnistParent} */
            node2
          );
          if (nodeAsParent.children && result[0] !== SKIP) {
            offset = (reverse ? nodeAsParent.children.length : -1) + step;
            grandparents = parents.concat(nodeAsParent);
            while (offset > -1 && offset < nodeAsParent.children.length) {
              const child = nodeAsParent.children[offset];
              subresult = factory(child, offset, grandparents)();
              if (subresult[0] === EXIT) {
                return subresult;
              }
              offset = typeof subresult[1] === "number" ? subresult[1] : offset + step;
            }
          }
        }
        return result;
      }
    }
  }
  function toResult(value) {
    if (Array.isArray(value)) {
      return value;
    }
    if (typeof value === "number") {
      return [CONTINUE, value];
    }
    return value === null || value === void 0 ? empty : [value];
  }
  function visit(tree, testOrVisitor, visitorOrReverse, maybeReverse) {
    let reverse;
    let test;
    let visitor;
    if (typeof testOrVisitor === "function" && typeof visitorOrReverse !== "function") {
      test = void 0;
      visitor = testOrVisitor;
      reverse = visitorOrReverse;
    } else {
      test = testOrVisitor;
      visitor = visitorOrReverse;
      reverse = maybeReverse;
    }
    visitParents(tree, test, overload, reverse);
    function overload(node2, parents) {
      const parent = parents[parents.length - 1];
      const index2 = parent ? parent.children.indexOf(node2) : void 0;
      return visitor(node2, index2, parent);
    }
  }
  const own$1 = {}.hasOwnProperty;
  const emptyOptions$1 = {};
  function createState(tree, options) {
    const settings = options || emptyOptions$1;
    const definitionById = /* @__PURE__ */ new Map();
    const footnoteById = /* @__PURE__ */ new Map();
    const footnoteCounts = /* @__PURE__ */ new Map();
    const handlers$1 = { ...handlers, ...settings.handlers };
    const state = {
      all: all2,
      applyData,
      definitionById,
      footnoteById,
      footnoteCounts,
      footnoteOrder: [],
      handlers: handlers$1,
      one: one2,
      options: settings,
      patch,
      wrap: wrap$1
    };
    visit(tree, function(node2) {
      if (node2.type === "definition" || node2.type === "footnoteDefinition") {
        const map2 = node2.type === "definition" ? definitionById : footnoteById;
        const id = String(node2.identifier).toUpperCase();
        if (!map2.has(id)) {
          map2.set(id, node2);
        }
      }
    });
    return state;
    function one2(node2, parent) {
      const type = node2.type;
      const handle2 = state.handlers[type];
      if (own$1.call(state.handlers, type) && handle2) {
        return handle2(state, node2, parent);
      }
      if (state.options.passThrough && state.options.passThrough.includes(type)) {
        if ("children" in node2) {
          const { children, ...shallow } = node2;
          const result = structuredClone$1(shallow);
          result.children = state.all(node2);
          return result;
        }
        return structuredClone$1(node2);
      }
      const unknown = state.options.unknownHandler || defaultUnknownHandler;
      return unknown(state, node2, parent);
    }
    function all2(parent) {
      const values = [];
      if ("children" in parent) {
        const nodes = parent.children;
        let index2 = -1;
        while (++index2 < nodes.length) {
          const result = state.one(nodes[index2], parent);
          if (result) {
            if (index2 && nodes[index2 - 1].type === "break") {
              if (!Array.isArray(result) && result.type === "text") {
                result.value = trimMarkdownSpaceStart(result.value);
              }
              if (!Array.isArray(result) && result.type === "element") {
                const head = result.children[0];
                if (head && head.type === "text") {
                  head.value = trimMarkdownSpaceStart(head.value);
                }
              }
            }
            if (Array.isArray(result)) {
              values.push(...result);
            } else {
              values.push(result);
            }
          }
        }
      }
      return values;
    }
  }
  function patch(from, to) {
    if (from.position) to.position = position$1(from);
  }
  function applyData(from, to) {
    let result = to;
    if (from && from.data) {
      const hName = from.data.hName;
      const hChildren = from.data.hChildren;
      const hProperties = from.data.hProperties;
      if (typeof hName === "string") {
        if (result.type === "element") {
          result.tagName = hName;
        } else {
          const children = "children" in result ? result.children : [result];
          result = { type: "element", tagName: hName, properties: {}, children };
        }
      }
      if (result.type === "element" && hProperties) {
        Object.assign(result.properties, structuredClone$1(hProperties));
      }
      if ("children" in result && result.children && hChildren !== null && hChildren !== void 0) {
        result.children = hChildren;
      }
    }
    return result;
  }
  function defaultUnknownHandler(state, node2) {
    const data = node2.data || {};
    const result = "value" in node2 && !(own$1.call(data, "hProperties") || own$1.call(data, "hChildren")) ? { type: "text", value: node2.value } : {
      type: "element",
      tagName: "div",
      properties: {},
      children: state.all(node2)
    };
    state.patch(node2, result);
    return state.applyData(node2, result);
  }
  function wrap$1(nodes, loose) {
    const result = [];
    let index2 = -1;
    if (loose) {
      result.push({ type: "text", value: "\n" });
    }
    while (++index2 < nodes.length) {
      if (index2) result.push({ type: "text", value: "\n" });
      result.push(nodes[index2]);
    }
    if (loose && nodes.length > 0) {
      result.push({ type: "text", value: "\n" });
    }
    return result;
  }
  function trimMarkdownSpaceStart(value) {
    let index2 = 0;
    let code2 = value.charCodeAt(index2);
    while (code2 === 9 || code2 === 32) {
      index2++;
      code2 = value.charCodeAt(index2);
    }
    return value.slice(index2);
  }
  function toHast(tree, options) {
    const state = createState(tree, options);
    const node2 = state.one(tree, void 0);
    const foot = footer(state);
    const result = Array.isArray(node2) ? { type: "root", children: node2 } : node2 || { type: "root", children: [] };
    if (foot) {
      result.children.push({ type: "text", value: "\n" }, foot);
    }
    return result;
  }
  function remarkRehype(destination, options) {
    if (destination && "run" in destination) {
      return async function(tree, file) {
        const hastTree = (
          /** @type {HastRoot} */
          toHast(tree, { file, ...options })
        );
        await destination.run(hastTree, file);
      };
    }
    return function(tree, file) {
      return (
        /** @type {HastRoot} */
        toHast(tree, { file, ...destination || options })
      );
    };
  }
  function bail(error) {
    if (error) {
      throw error;
    }
  }
  function isPlainObject(value) {
    if (typeof value !== "object" || value === null) {
      return false;
    }
    const prototype = Object.getPrototypeOf(value);
    return (prototype === null || prototype === Object.prototype || Object.getPrototypeOf(prototype) === null) && !(Symbol.toStringTag in value) && !(Symbol.iterator in value);
  }
  function trough() {
    const fns = [];
    const pipeline = { run, use };
    return pipeline;
    function run(...values) {
      let middlewareIndex = -1;
      const callback = values.pop();
      if (typeof callback !== "function") {
        throw new TypeError("Expected function as last argument, not " + callback);
      }
      next(null, ...values);
      function next(error, ...output) {
        const fn = fns[++middlewareIndex];
        let index2 = -1;
        if (error) {
          callback(error);
          return;
        }
        while (++index2 < values.length) {
          if (output[index2] === null || output[index2] === void 0) {
            output[index2] = values[index2];
          }
        }
        values = output;
        if (fn) {
          wrap(fn, next)(...output);
        } else {
          callback(null, ...output);
        }
      }
    }
    function use(middelware) {
      if (typeof middelware !== "function") {
        throw new TypeError(
          "Expected `middelware` to be a function, not " + middelware
        );
      }
      fns.push(middelware);
      return pipeline;
    }
  }
  function wrap(middleware, callback) {
    let called;
    return wrapped;
    function wrapped(...parameters) {
      const fnExpectsCallback = middleware.length > parameters.length;
      let result;
      if (fnExpectsCallback) {
        parameters.push(done);
      }
      try {
        result = middleware.apply(this, parameters);
      } catch (error) {
        const exception = (
          /** @type {Error} */
          error
        );
        if (fnExpectsCallback && called) {
          throw exception;
        }
        return done(exception);
      }
      if (!fnExpectsCallback) {
        if (result && result.then && typeof result.then === "function") {
          result.then(then, done);
        } else if (result instanceof Error) {
          done(result);
        } else {
          then(result);
        }
      }
    }
    function done(error, ...output) {
      if (!called) {
        called = true;
        callback(error, ...output);
      }
    }
    function then(value) {
      done(null, value);
    }
  }
  const minpath = { basename, dirname, extname, join, sep: "/" };
  function basename(path2, extname2) {
    if (extname2 !== void 0 && typeof extname2 !== "string") {
      throw new TypeError('"ext" argument must be a string');
    }
    assertPath$1(path2);
    let start = 0;
    let end = -1;
    let index2 = path2.length;
    let seenNonSlash;
    if (extname2 === void 0 || extname2.length === 0 || extname2.length > path2.length) {
      while (index2--) {
        if (path2.codePointAt(index2) === 47) {
          if (seenNonSlash) {
            start = index2 + 1;
            break;
          }
        } else if (end < 0) {
          seenNonSlash = true;
          end = index2 + 1;
        }
      }
      return end < 0 ? "" : path2.slice(start, end);
    }
    if (extname2 === path2) {
      return "";
    }
    let firstNonSlashEnd = -1;
    let extnameIndex = extname2.length - 1;
    while (index2--) {
      if (path2.codePointAt(index2) === 47) {
        if (seenNonSlash) {
          start = index2 + 1;
          break;
        }
      } else {
        if (firstNonSlashEnd < 0) {
          seenNonSlash = true;
          firstNonSlashEnd = index2 + 1;
        }
        if (extnameIndex > -1) {
          if (path2.codePointAt(index2) === extname2.codePointAt(extnameIndex--)) {
            if (extnameIndex < 0) {
              end = index2;
            }
          } else {
            extnameIndex = -1;
            end = firstNonSlashEnd;
          }
        }
      }
    }
    if (start === end) {
      end = firstNonSlashEnd;
    } else if (end < 0) {
      end = path2.length;
    }
    return path2.slice(start, end);
  }
  function dirname(path2) {
    assertPath$1(path2);
    if (path2.length === 0) {
      return ".";
    }
    let end = -1;
    let index2 = path2.length;
    let unmatchedSlash;
    while (--index2) {
      if (path2.codePointAt(index2) === 47) {
        if (unmatchedSlash) {
          end = index2;
          break;
        }
      } else if (!unmatchedSlash) {
        unmatchedSlash = true;
      }
    }
    return end < 0 ? path2.codePointAt(0) === 47 ? "/" : "." : end === 1 && path2.codePointAt(0) === 47 ? "//" : path2.slice(0, end);
  }
  function extname(path2) {
    assertPath$1(path2);
    let index2 = path2.length;
    let end = -1;
    let startPart = 0;
    let startDot = -1;
    let preDotState = 0;
    let unmatchedSlash;
    while (index2--) {
      const code2 = path2.codePointAt(index2);
      if (code2 === 47) {
        if (unmatchedSlash) {
          startPart = index2 + 1;
          break;
        }
        continue;
      }
      if (end < 0) {
        unmatchedSlash = true;
        end = index2 + 1;
      }
      if (code2 === 46) {
        if (startDot < 0) {
          startDot = index2;
        } else if (preDotState !== 1) {
          preDotState = 1;
        }
      } else if (startDot > -1) {
        preDotState = -1;
      }
    }
    if (startDot < 0 || end < 0 || // We saw a non-dot character immediately before the dot.
    preDotState === 0 || // The (right-most) trimmed path component is exactly `..`.
    preDotState === 1 && startDot === end - 1 && startDot === startPart + 1) {
      return "";
    }
    return path2.slice(startDot, end);
  }
  function join(...segments) {
    let index2 = -1;
    let joined;
    while (++index2 < segments.length) {
      assertPath$1(segments[index2]);
      if (segments[index2]) {
        joined = joined === void 0 ? segments[index2] : joined + "/" + segments[index2];
      }
    }
    return joined === void 0 ? "." : normalize(joined);
  }
  function normalize(path2) {
    assertPath$1(path2);
    const absolute = path2.codePointAt(0) === 47;
    let value = normalizeString(path2, !absolute);
    if (value.length === 0 && !absolute) {
      value = ".";
    }
    if (value.length > 0 && path2.codePointAt(path2.length - 1) === 47) {
      value += "/";
    }
    return absolute ? "/" + value : value;
  }
  function normalizeString(path2, allowAboveRoot) {
    let result = "";
    let lastSegmentLength = 0;
    let lastSlash = -1;
    let dots = 0;
    let index2 = -1;
    let code2;
    let lastSlashIndex;
    while (++index2 <= path2.length) {
      if (index2 < path2.length) {
        code2 = path2.codePointAt(index2);
      } else if (code2 === 47) {
        break;
      } else {
        code2 = 47;
      }
      if (code2 === 47) {
        if (lastSlash === index2 - 1 || dots === 1) ;
        else if (lastSlash !== index2 - 1 && dots === 2) {
          if (result.length < 2 || lastSegmentLength !== 2 || result.codePointAt(result.length - 1) !== 46 || result.codePointAt(result.length - 2) !== 46) {
            if (result.length > 2) {
              lastSlashIndex = result.lastIndexOf("/");
              if (lastSlashIndex !== result.length - 1) {
                if (lastSlashIndex < 0) {
                  result = "";
                  lastSegmentLength = 0;
                } else {
                  result = result.slice(0, lastSlashIndex);
                  lastSegmentLength = result.length - 1 - result.lastIndexOf("/");
                }
                lastSlash = index2;
                dots = 0;
                continue;
              }
            } else if (result.length > 0) {
              result = "";
              lastSegmentLength = 0;
              lastSlash = index2;
              dots = 0;
              continue;
            }
          }
          if (allowAboveRoot) {
            result = result.length > 0 ? result + "/.." : "..";
            lastSegmentLength = 2;
          }
        } else {
          if (result.length > 0) {
            result += "/" + path2.slice(lastSlash + 1, index2);
          } else {
            result = path2.slice(lastSlash + 1, index2);
          }
          lastSegmentLength = index2 - lastSlash - 1;
        }
        lastSlash = index2;
        dots = 0;
      } else if (code2 === 46 && dots > -1) {
        dots++;
      } else {
        dots = -1;
      }
    }
    return result;
  }
  function assertPath$1(path2) {
    if (typeof path2 !== "string") {
      throw new TypeError(
        "Path must be a string. Received " + JSON.stringify(path2)
      );
    }
  }
  const minproc = { cwd };
  function cwd() {
    return "/";
  }
  function isUrl(fileUrlOrPath) {
    return Boolean(
      fileUrlOrPath !== null && typeof fileUrlOrPath === "object" && "href" in fileUrlOrPath && fileUrlOrPath.href && "protocol" in fileUrlOrPath && fileUrlOrPath.protocol && // @ts-expect-error: indexing is fine.
      fileUrlOrPath.auth === void 0
    );
  }
  function urlToPath(path2) {
    if (typeof path2 === "string") {
      path2 = new URL(path2);
    } else if (!isUrl(path2)) {
      const error = new TypeError(
        'The "path" argument must be of type string or an instance of URL. Received `' + path2 + "`"
      );
      error.code = "ERR_INVALID_ARG_TYPE";
      throw error;
    }
    if (path2.protocol !== "file:") {
      const error = new TypeError("The URL must be of scheme file");
      error.code = "ERR_INVALID_URL_SCHEME";
      throw error;
    }
    return getPathFromURLPosix(path2);
  }
  function getPathFromURLPosix(url) {
    if (url.hostname !== "") {
      const error = new TypeError(
        'File URL host must be "localhost" or empty on darwin'
      );
      error.code = "ERR_INVALID_FILE_URL_HOST";
      throw error;
    }
    const pathname = url.pathname;
    let index2 = -1;
    while (++index2 < pathname.length) {
      if (pathname.codePointAt(index2) === 37 && pathname.codePointAt(index2 + 1) === 50) {
        const third = pathname.codePointAt(index2 + 2);
        if (third === 70 || third === 102) {
          const error = new TypeError(
            "File URL path must not include encoded / characters"
          );
          error.code = "ERR_INVALID_FILE_URL_PATH";
          throw error;
        }
      }
    }
    return decodeURIComponent(pathname);
  }
  const order = (
    /** @type {const} */
    [
      "history",
      "path",
      "basename",
      "stem",
      "extname",
      "dirname"
    ]
  );
  class VFile {
    /**
     * Create a new virtual file.
     *
     * `options` is treated as:
     *
     * *   `string` or `Uint8Array` — `{value: options}`
     * *   `URL` — `{path: options}`
     * *   `VFile` — shallow copies its data over to the new file
     * *   `object` — all fields are shallow copied over to the new file
     *
     * Path related fields are set in the following order (least specific to
     * most specific): `history`, `path`, `basename`, `stem`, `extname`,
     * `dirname`.
     *
     * You cannot set `dirname` or `extname` without setting either `history`,
     * `path`, `basename`, or `stem` too.
     *
     * @param {Compatible | null | undefined} [value]
     *   File value.
     * @returns
     *   New instance.
     */
    constructor(value) {
      let options;
      if (!value) {
        options = {};
      } else if (isUrl(value)) {
        options = { path: value };
      } else if (typeof value === "string" || isUint8Array$1(value)) {
        options = { value };
      } else {
        options = value;
      }
      this.cwd = "cwd" in options ? "" : minproc.cwd();
      this.data = {};
      this.history = [];
      this.messages = [];
      this.value;
      this.map;
      this.result;
      this.stored;
      let index2 = -1;
      while (++index2 < order.length) {
        const field2 = order[index2];
        if (field2 in options && options[field2] !== void 0 && options[field2] !== null) {
          this[field2] = field2 === "history" ? [...options[field2]] : options[field2];
        }
      }
      let field;
      for (field in options) {
        if (!order.includes(field)) {
          this[field] = options[field];
        }
      }
    }
    /**
     * Get the basename (including extname) (example: `'index.min.js'`).
     *
     * @returns {string | undefined}
     *   Basename.
     */
    get basename() {
      return typeof this.path === "string" ? minpath.basename(this.path) : void 0;
    }
    /**
     * Set basename (including extname) (`'index.min.js'`).
     *
     * Cannot contain path separators (`'/'` on unix, macOS, and browsers, `'\'`
     * on windows).
     * Cannot be nullified (use `file.path = file.dirname` instead).
     *
     * @param {string} basename
     *   Basename.
     * @returns {undefined}
     *   Nothing.
     */
    set basename(basename2) {
      assertNonEmpty(basename2, "basename");
      assertPart(basename2, "basename");
      this.path = minpath.join(this.dirname || "", basename2);
    }
    /**
     * Get the parent path (example: `'~'`).
     *
     * @returns {string | undefined}
     *   Dirname.
     */
    get dirname() {
      return typeof this.path === "string" ? minpath.dirname(this.path) : void 0;
    }
    /**
     * Set the parent path (example: `'~'`).
     *
     * Cannot be set if there’s no `path` yet.
     *
     * @param {string | undefined} dirname
     *   Dirname.
     * @returns {undefined}
     *   Nothing.
     */
    set dirname(dirname2) {
      assertPath(this.basename, "dirname");
      this.path = minpath.join(dirname2 || "", this.basename);
    }
    /**
     * Get the extname (including dot) (example: `'.js'`).
     *
     * @returns {string | undefined}
     *   Extname.
     */
    get extname() {
      return typeof this.path === "string" ? minpath.extname(this.path) : void 0;
    }
    /**
     * Set the extname (including dot) (example: `'.js'`).
     *
     * Cannot contain path separators (`'/'` on unix, macOS, and browsers, `'\'`
     * on windows).
     * Cannot be set if there’s no `path` yet.
     *
     * @param {string | undefined} extname
     *   Extname.
     * @returns {undefined}
     *   Nothing.
     */
    set extname(extname2) {
      assertPart(extname2, "extname");
      assertPath(this.dirname, "extname");
      if (extname2) {
        if (extname2.codePointAt(0) !== 46) {
          throw new Error("`extname` must start with `.`");
        }
        if (extname2.includes(".", 1)) {
          throw new Error("`extname` cannot contain multiple dots");
        }
      }
      this.path = minpath.join(this.dirname, this.stem + (extname2 || ""));
    }
    /**
     * Get the full path (example: `'~/index.min.js'`).
     *
     * @returns {string}
     *   Path.
     */
    get path() {
      return this.history[this.history.length - 1];
    }
    /**
     * Set the full path (example: `'~/index.min.js'`).
     *
     * Cannot be nullified.
     * You can set a file URL (a `URL` object with a `file:` protocol) which will
     * be turned into a path with `url.fileURLToPath`.
     *
     * @param {URL | string} path
     *   Path.
     * @returns {undefined}
     *   Nothing.
     */
    set path(path2) {
      if (isUrl(path2)) {
        path2 = urlToPath(path2);
      }
      assertNonEmpty(path2, "path");
      if (this.path !== path2) {
        this.history.push(path2);
      }
    }
    /**
     * Get the stem (basename w/o extname) (example: `'index.min'`).
     *
     * @returns {string | undefined}
     *   Stem.
     */
    get stem() {
      return typeof this.path === "string" ? minpath.basename(this.path, this.extname) : void 0;
    }
    /**
     * Set the stem (basename w/o extname) (example: `'index.min'`).
     *
     * Cannot contain path separators (`'/'` on unix, macOS, and browsers, `'\'`
     * on windows).
     * Cannot be nullified (use `file.path = file.dirname` instead).
     *
     * @param {string} stem
     *   Stem.
     * @returns {undefined}
     *   Nothing.
     */
    set stem(stem) {
      assertNonEmpty(stem, "stem");
      assertPart(stem, "stem");
      this.path = minpath.join(this.dirname || "", stem + (this.extname || ""));
    }
    // Normal prototypal methods.
    /**
     * Create a fatal message for `reason` associated with the file.
     *
     * The `fatal` field of the message is set to `true` (error; file not usable)
     * and the `file` field is set to the current file path.
     * The message is added to the `messages` field on `file`.
     *
     * > 🪦 **Note**: also has obsolete signatures.
     *
     * @overload
     * @param {string} reason
     * @param {MessageOptions | null | undefined} [options]
     * @returns {never}
     *
     * @overload
     * @param {string} reason
     * @param {Node | NodeLike | null | undefined} parent
     * @param {string | null | undefined} [origin]
     * @returns {never}
     *
     * @overload
     * @param {string} reason
     * @param {Point | Position | null | undefined} place
     * @param {string | null | undefined} [origin]
     * @returns {never}
     *
     * @overload
     * @param {string} reason
     * @param {string | null | undefined} [origin]
     * @returns {never}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {Node | NodeLike | null | undefined} parent
     * @param {string | null | undefined} [origin]
     * @returns {never}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {Point | Position | null | undefined} place
     * @param {string | null | undefined} [origin]
     * @returns {never}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {string | null | undefined} [origin]
     * @returns {never}
     *
     * @param {Error | VFileMessage | string} causeOrReason
     *   Reason for message, should use markdown.
     * @param {Node | NodeLike | MessageOptions | Point | Position | string | null | undefined} [optionsOrParentOrPlace]
     *   Configuration (optional).
     * @param {string | null | undefined} [origin]
     *   Place in code where the message originates (example:
     *   `'my-package:my-rule'` or `'my-rule'`).
     * @returns {never}
     *   Never.
     * @throws {VFileMessage}
     *   Message.
     */
    fail(causeOrReason, optionsOrParentOrPlace, origin) {
      const message = this.message(causeOrReason, optionsOrParentOrPlace, origin);
      message.fatal = true;
      throw message;
    }
    /**
     * Create an info message for `reason` associated with the file.
     *
     * The `fatal` field of the message is set to `undefined` (info; change
     * likely not needed) and the `file` field is set to the current file path.
     * The message is added to the `messages` field on `file`.
     *
     * > 🪦 **Note**: also has obsolete signatures.
     *
     * @overload
     * @param {string} reason
     * @param {MessageOptions | null | undefined} [options]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {string} reason
     * @param {Node | NodeLike | null | undefined} parent
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {string} reason
     * @param {Point | Position | null | undefined} place
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {string} reason
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {Node | NodeLike | null | undefined} parent
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {Point | Position | null | undefined} place
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @param {Error | VFileMessage | string} causeOrReason
     *   Reason for message, should use markdown.
     * @param {Node | NodeLike | MessageOptions | Point | Position | string | null | undefined} [optionsOrParentOrPlace]
     *   Configuration (optional).
     * @param {string | null | undefined} [origin]
     *   Place in code where the message originates (example:
     *   `'my-package:my-rule'` or `'my-rule'`).
     * @returns {VFileMessage}
     *   Message.
     */
    info(causeOrReason, optionsOrParentOrPlace, origin) {
      const message = this.message(causeOrReason, optionsOrParentOrPlace, origin);
      message.fatal = void 0;
      return message;
    }
    /**
     * Create a message for `reason` associated with the file.
     *
     * The `fatal` field of the message is set to `false` (warning; change may be
     * needed) and the `file` field is set to the current file path.
     * The message is added to the `messages` field on `file`.
     *
     * > 🪦 **Note**: also has obsolete signatures.
     *
     * @overload
     * @param {string} reason
     * @param {MessageOptions | null | undefined} [options]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {string} reason
     * @param {Node | NodeLike | null | undefined} parent
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {string} reason
     * @param {Point | Position | null | undefined} place
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {string} reason
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {Node | NodeLike | null | undefined} parent
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {Point | Position | null | undefined} place
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @overload
     * @param {Error | VFileMessage} cause
     * @param {string | null | undefined} [origin]
     * @returns {VFileMessage}
     *
     * @param {Error | VFileMessage | string} causeOrReason
     *   Reason for message, should use markdown.
     * @param {Node | NodeLike | MessageOptions | Point | Position | string | null | undefined} [optionsOrParentOrPlace]
     *   Configuration (optional).
     * @param {string | null | undefined} [origin]
     *   Place in code where the message originates (example:
     *   `'my-package:my-rule'` or `'my-rule'`).
     * @returns {VFileMessage}
     *   Message.
     */
    message(causeOrReason, optionsOrParentOrPlace, origin) {
      const message = new VFileMessage(
        // @ts-expect-error: the overloads are fine.
        causeOrReason,
        optionsOrParentOrPlace,
        origin
      );
      if (this.path) {
        message.name = this.path + ":" + message.name;
        message.file = this.path;
      }
      message.fatal = false;
      this.messages.push(message);
      return message;
    }
    /**
     * Serialize the file.
     *
     * > **Note**: which encodings are supported depends on the engine.
     * > For info on Node.js, see:
     * > <https://nodejs.org/api/util.html#whatwg-supported-encodings>.
     *
     * @param {string | null | undefined} [encoding='utf8']
     *   Character encoding to understand `value` as when it’s a `Uint8Array`
     *   (default: `'utf-8'`).
     * @returns {string}
     *   Serialized file.
     */
    toString(encoding) {
      if (this.value === void 0) {
        return "";
      }
      if (typeof this.value === "string") {
        return this.value;
      }
      const decoder = new TextDecoder(encoding || void 0);
      return decoder.decode(this.value);
    }
  }
  function assertPart(part, name2) {
    if (part && part.includes(minpath.sep)) {
      throw new Error(
        "`" + name2 + "` cannot be a path: did not expect `" + minpath.sep + "`"
      );
    }
  }
  function assertNonEmpty(part, name2) {
    if (!part) {
      throw new Error("`" + name2 + "` cannot be empty");
    }
  }
  function assertPath(path2, name2) {
    if (!path2) {
      throw new Error("Setting `" + name2 + "` requires `path` to be set too");
    }
  }
  function isUint8Array$1(value) {
    return Boolean(
      value && typeof value === "object" && "byteLength" in value && "byteOffset" in value
    );
  }
  const CallableInstance = (
    /**
     * @type {new <Parameters extends Array<unknown>, Result>(property: string | symbol) => (...parameters: Parameters) => Result}
     */
    /** @type {unknown} */
    /**
     * @this {Function}
     * @param {string | symbol} property
     * @returns {(...parameters: Array<unknown>) => unknown}
     */
    function(property) {
      const self2 = this;
      const constr = self2.constructor;
      const proto = (
        /** @type {Record<string | symbol, Function>} */
        // Prototypes do exist.
        // type-coverage:ignore-next-line
        constr.prototype
      );
      const func = proto[property];
      const apply = function() {
        return func.apply(apply, arguments);
      };
      Object.setPrototypeOf(apply, proto);
      const names = Object.getOwnPropertyNames(func);
      for (const p of names) {
        const descriptor = Object.getOwnPropertyDescriptor(func, p);
        if (descriptor) Object.defineProperty(apply, p, descriptor);
      }
      return apply;
    }
  );
  const own = {}.hasOwnProperty;
  class Processor extends CallableInstance {
    /**
     * Create a processor.
     */
    constructor() {
      super("copy");
      this.Compiler = void 0;
      this.Parser = void 0;
      this.attachers = [];
      this.compiler = void 0;
      this.freezeIndex = -1;
      this.frozen = void 0;
      this.namespace = {};
      this.parser = void 0;
      this.transformers = trough();
    }
    /**
     * Copy a processor.
     *
     * @deprecated
     *   This is a private internal method and should not be used.
     * @returns {Processor<ParseTree, HeadTree, TailTree, CompileTree, CompileResult>}
     *   New *unfrozen* processor ({@link Processor `Processor`}) that is
     *   configured to work the same as its ancestor.
     *   When the descendant processor is configured in the future it does not
     *   affect the ancestral processor.
     */
    copy() {
      const destination = (
        /** @type {Processor<ParseTree, HeadTree, TailTree, CompileTree, CompileResult>} */
        new Processor()
      );
      let index2 = -1;
      while (++index2 < this.attachers.length) {
        const attacher = this.attachers[index2];
        destination.use(...attacher);
      }
      destination.data(structuredClone$1(this.namespace));
      return destination;
    }
    /**
     * Configure the processor with info available to all plugins.
     * Information is stored in an object.
     *
     * Typically, options can be given to a specific plugin, but sometimes it
     * makes sense to have information shared with several plugins.
     * For example, a list of HTML elements that are self-closing, which is
     * needed during all phases.
     *
     * > 👉 **Note**: setting information cannot occur on *frozen* processors.
     * > Call the processor first to create a new unfrozen processor.
     *
     * > 👉 **Note**: to register custom data in TypeScript, augment the
     * > {@link Data `Data`} interface.
     *
     * @example
     *   This example show how to get and set info:
     *
     *   ```js
     *   import {unified} from 'unified'
     *
     *   const processor = unified().data('alpha', 'bravo')
     *
     *   processor.data('alpha') // => 'bravo'
     *
     *   processor.data() // => {alpha: 'bravo'}
     *
     *   processor.data({charlie: 'delta'})
     *
     *   processor.data() // => {charlie: 'delta'}
     *   ```
     *
     * @template {keyof Data} Key
     *
     * @overload
     * @returns {Data}
     *
     * @overload
     * @param {Data} dataset
     * @returns {Processor<ParseTree, HeadTree, TailTree, CompileTree, CompileResult>}
     *
     * @overload
     * @param {Key} key
     * @returns {Data[Key]}
     *
     * @overload
     * @param {Key} key
     * @param {Data[Key]} value
     * @returns {Processor<ParseTree, HeadTree, TailTree, CompileTree, CompileResult>}
     *
     * @param {Data | Key} [key]
     *   Key to get or set, or entire dataset to set, or nothing to get the
     *   entire dataset (optional).
     * @param {Data[Key]} [value]
     *   Value to set (optional).
     * @returns {unknown}
     *   The current processor when setting, the value at `key` when getting, or
     *   the entire dataset when getting without key.
     */
    data(key, value) {
      if (typeof key === "string") {
        if (arguments.length === 2) {
          assertUnfrozen("data", this.frozen);
          this.namespace[key] = value;
          return this;
        }
        return own.call(this.namespace, key) && this.namespace[key] || void 0;
      }
      if (key) {
        assertUnfrozen("data", this.frozen);
        this.namespace = key;
        return this;
      }
      return this.namespace;
    }
    /**
     * Freeze a processor.
     *
     * Frozen processors are meant to be extended and not to be configured
     * directly.
     *
     * When a processor is frozen it cannot be unfrozen.
     * New processors working the same way can be created by calling the
     * processor.
     *
     * It’s possible to freeze processors explicitly by calling `.freeze()`.
     * Processors freeze automatically when `.parse()`, `.run()`, `.runSync()`,
     * `.stringify()`, `.process()`, or `.processSync()` are called.
     *
     * @returns {Processor<ParseTree, HeadTree, TailTree, CompileTree, CompileResult>}
     *   The current processor.
     */
    freeze() {
      if (this.frozen) {
        return this;
      }
      const self2 = (
        /** @type {Processor} */
        /** @type {unknown} */
        this
      );
      while (++this.freezeIndex < this.attachers.length) {
        const [attacher, ...options] = this.attachers[this.freezeIndex];
        if (options[0] === false) {
          continue;
        }
        if (options[0] === true) {
          options[0] = void 0;
        }
        const transformer = attacher.call(self2, ...options);
        if (typeof transformer === "function") {
          this.transformers.use(transformer);
        }
      }
      this.frozen = true;
      this.freezeIndex = Number.POSITIVE_INFINITY;
      return this;
    }
    /**
     * Parse text to a syntax tree.
     *
     * > 👉 **Note**: `parse` freezes the processor if not already *frozen*.
     *
     * > 👉 **Note**: `parse` performs the parse phase, not the run phase or other
     * > phases.
     *
     * @param {Compatible | undefined} [file]
     *   file to parse (optional); typically `string` or `VFile`; any value
     *   accepted as `x` in `new VFile(x)`.
     * @returns {ParseTree extends undefined ? Node : ParseTree}
     *   Syntax tree representing `file`.
     */
    parse(file) {
      this.freeze();
      const realFile = vfile(file);
      const parser = this.parser || this.Parser;
      assertParser("parse", parser);
      return parser(String(realFile), realFile);
    }
    /**
     * Process the given file as configured on the processor.
     *
     * > 👉 **Note**: `process` freezes the processor if not already *frozen*.
     *
     * > 👉 **Note**: `process` performs the parse, run, and stringify phases.
     *
     * @overload
     * @param {Compatible | undefined} file
     * @param {ProcessCallback<VFileWithOutput<CompileResult>>} done
     * @returns {undefined}
     *
     * @overload
     * @param {Compatible | undefined} [file]
     * @returns {Promise<VFileWithOutput<CompileResult>>}
     *
     * @param {Compatible | undefined} [file]
     *   File (optional); typically `string` or `VFile`]; any value accepted as
     *   `x` in `new VFile(x)`.
     * @param {ProcessCallback<VFileWithOutput<CompileResult>> | undefined} [done]
     *   Callback (optional).
     * @returns {Promise<VFile> | undefined}
     *   Nothing if `done` is given.
     *   Otherwise a promise, rejected with a fatal error or resolved with the
     *   processed file.
     *
     *   The parsed, transformed, and compiled value is available at
     *   `file.value` (see note).
     *
     *   > 👉 **Note**: unified typically compiles by serializing: most
     *   > compilers return `string` (or `Uint8Array`).
     *   > Some compilers, such as the one configured with
     *   > [`rehype-react`][rehype-react], return other values (in this case, a
     *   > React tree).
     *   > If you’re using a compiler that doesn’t serialize, expect different
     *   > result values.
     *   >
     *   > To register custom results in TypeScript, add them to
     *   > {@link CompileResultMap `CompileResultMap`}.
     *
     *   [rehype-react]: https://github.com/rehypejs/rehype-react
     */
    process(file, done) {
      const self2 = this;
      this.freeze();
      assertParser("process", this.parser || this.Parser);
      assertCompiler("process", this.compiler || this.Compiler);
      return done ? executor(void 0, done) : new Promise(executor);
      function executor(resolve, reject) {
        const realFile = vfile(file);
        const parseTree = (
          /** @type {HeadTree extends undefined ? Node : HeadTree} */
          /** @type {unknown} */
          self2.parse(realFile)
        );
        self2.run(parseTree, realFile, function(error, tree, file2) {
          if (error || !tree || !file2) {
            return realDone(error);
          }
          const compileTree = (
            /** @type {CompileTree extends undefined ? Node : CompileTree} */
            /** @type {unknown} */
            tree
          );
          const compileResult = self2.stringify(compileTree, file2);
          if (looksLikeAValue(compileResult)) {
            file2.value = compileResult;
          } else {
            file2.result = compileResult;
          }
          realDone(
            error,
            /** @type {VFileWithOutput<CompileResult>} */
            file2
          );
        });
        function realDone(error, file2) {
          if (error || !file2) {
            reject(error);
          } else if (resolve) {
            resolve(file2);
          } else {
            done(void 0, file2);
          }
        }
      }
    }
    /**
     * Process the given file as configured on the processor.
     *
     * An error is thrown if asynchronous transforms are configured.
     *
     * > 👉 **Note**: `processSync` freezes the processor if not already *frozen*.
     *
     * > 👉 **Note**: `processSync` performs the parse, run, and stringify phases.
     *
     * @param {Compatible | undefined} [file]
     *   File (optional); typically `string` or `VFile`; any value accepted as
     *   `x` in `new VFile(x)`.
     * @returns {VFileWithOutput<CompileResult>}
     *   The processed file.
     *
     *   The parsed, transformed, and compiled value is available at
     *   `file.value` (see note).
     *
     *   > 👉 **Note**: unified typically compiles by serializing: most
     *   > compilers return `string` (or `Uint8Array`).
     *   > Some compilers, such as the one configured with
     *   > [`rehype-react`][rehype-react], return other values (in this case, a
     *   > React tree).
     *   > If you’re using a compiler that doesn’t serialize, expect different
     *   > result values.
     *   >
     *   > To register custom results in TypeScript, add them to
     *   > {@link CompileResultMap `CompileResultMap`}.
     *
     *   [rehype-react]: https://github.com/rehypejs/rehype-react
     */
    processSync(file) {
      let complete = false;
      let result;
      this.freeze();
      assertParser("processSync", this.parser || this.Parser);
      assertCompiler("processSync", this.compiler || this.Compiler);
      this.process(file, realDone);
      assertDone("processSync", "process", complete);
      return result;
      function realDone(error, file2) {
        complete = true;
        bail(error);
        result = file2;
      }
    }
    /**
     * Run *transformers* on a syntax tree.
     *
     * > 👉 **Note**: `run` freezes the processor if not already *frozen*.
     *
     * > 👉 **Note**: `run` performs the run phase, not other phases.
     *
     * @overload
     * @param {HeadTree extends undefined ? Node : HeadTree} tree
     * @param {RunCallback<TailTree extends undefined ? Node : TailTree>} done
     * @returns {undefined}
     *
     * @overload
     * @param {HeadTree extends undefined ? Node : HeadTree} tree
     * @param {Compatible | undefined} file
     * @param {RunCallback<TailTree extends undefined ? Node : TailTree>} done
     * @returns {undefined}
     *
     * @overload
     * @param {HeadTree extends undefined ? Node : HeadTree} tree
     * @param {Compatible | undefined} [file]
     * @returns {Promise<TailTree extends undefined ? Node : TailTree>}
     *
     * @param {HeadTree extends undefined ? Node : HeadTree} tree
     *   Tree to transform and inspect.
     * @param {(
     *   RunCallback<TailTree extends undefined ? Node : TailTree> |
     *   Compatible
     * )} [file]
     *   File associated with `node` (optional); any value accepted as `x` in
     *   `new VFile(x)`.
     * @param {RunCallback<TailTree extends undefined ? Node : TailTree>} [done]
     *   Callback (optional).
     * @returns {Promise<TailTree extends undefined ? Node : TailTree> | undefined}
     *   Nothing if `done` is given.
     *   Otherwise, a promise rejected with a fatal error or resolved with the
     *   transformed tree.
     */
    run(tree, file, done) {
      assertNode(tree);
      this.freeze();
      const transformers = this.transformers;
      if (!done && typeof file === "function") {
        done = file;
        file = void 0;
      }
      return done ? executor(void 0, done) : new Promise(executor);
      function executor(resolve, reject) {
        const realFile = vfile(file);
        transformers.run(tree, realFile, realDone);
        function realDone(error, outputTree, file2) {
          const resultingTree = (
            /** @type {TailTree extends undefined ? Node : TailTree} */
            outputTree || tree
          );
          if (error) {
            reject(error);
          } else if (resolve) {
            resolve(resultingTree);
          } else {
            done(void 0, resultingTree, file2);
          }
        }
      }
    }
    /**
     * Run *transformers* on a syntax tree.
     *
     * An error is thrown if asynchronous transforms are configured.
     *
     * > 👉 **Note**: `runSync` freezes the processor if not already *frozen*.
     *
     * > 👉 **Note**: `runSync` performs the run phase, not other phases.
     *
     * @param {HeadTree extends undefined ? Node : HeadTree} tree
     *   Tree to transform and inspect.
     * @param {Compatible | undefined} [file]
     *   File associated with `node` (optional); any value accepted as `x` in
     *   `new VFile(x)`.
     * @returns {TailTree extends undefined ? Node : TailTree}
     *   Transformed tree.
     */
    runSync(tree, file) {
      let complete = false;
      let result;
      this.run(tree, file, realDone);
      assertDone("runSync", "run", complete);
      return result;
      function realDone(error, tree2) {
        bail(error);
        result = tree2;
        complete = true;
      }
    }
    /**
     * Compile a syntax tree.
     *
     * > 👉 **Note**: `stringify` freezes the processor if not already *frozen*.
     *
     * > 👉 **Note**: `stringify` performs the stringify phase, not the run phase
     * > or other phases.
     *
     * @param {CompileTree extends undefined ? Node : CompileTree} tree
     *   Tree to compile.
     * @param {Compatible | undefined} [file]
     *   File associated with `node` (optional); any value accepted as `x` in
     *   `new VFile(x)`.
     * @returns {CompileResult extends undefined ? Value : CompileResult}
     *   Textual representation of the tree (see note).
     *
     *   > 👉 **Note**: unified typically compiles by serializing: most compilers
     *   > return `string` (or `Uint8Array`).
     *   > Some compilers, such as the one configured with
     *   > [`rehype-react`][rehype-react], return other values (in this case, a
     *   > React tree).
     *   > If you’re using a compiler that doesn’t serialize, expect different
     *   > result values.
     *   >
     *   > To register custom results in TypeScript, add them to
     *   > {@link CompileResultMap `CompileResultMap`}.
     *
     *   [rehype-react]: https://github.com/rehypejs/rehype-react
     */
    stringify(tree, file) {
      this.freeze();
      const realFile = vfile(file);
      const compiler2 = this.compiler || this.Compiler;
      assertCompiler("stringify", compiler2);
      assertNode(tree);
      return compiler2(tree, realFile);
    }
    /**
     * Configure the processor to use a plugin, a list of usable values, or a
     * preset.
     *
     * If the processor is already using a plugin, the previous plugin
     * configuration is changed based on the options that are passed in.
     * In other words, the plugin is not added a second time.
     *
     * > 👉 **Note**: `use` cannot be called on *frozen* processors.
     * > Call the processor first to create a new unfrozen processor.
     *
     * @example
     *   There are many ways to pass plugins to `.use()`.
     *   This example gives an overview:
     *
     *   ```js
     *   import {unified} from 'unified'
     *
     *   unified()
     *     // Plugin with options:
     *     .use(pluginA, {x: true, y: true})
     *     // Passing the same plugin again merges configuration (to `{x: true, y: false, z: true}`):
     *     .use(pluginA, {y: false, z: true})
     *     // Plugins:
     *     .use([pluginB, pluginC])
     *     // Two plugins, the second with options:
     *     .use([pluginD, [pluginE, {}]])
     *     // Preset with plugins and settings:
     *     .use({plugins: [pluginF, [pluginG, {}]], settings: {position: false}})
     *     // Settings only:
     *     .use({settings: {position: false}})
     *   ```
     *
     * @template {Array<unknown>} [Parameters=[]]
     * @template {Node | string | undefined} [Input=undefined]
     * @template [Output=Input]
     *
     * @overload
     * @param {Preset | null | undefined} [preset]
     * @returns {Processor<ParseTree, HeadTree, TailTree, CompileTree, CompileResult>}
     *
     * @overload
     * @param {PluggableList} list
     * @returns {Processor<ParseTree, HeadTree, TailTree, CompileTree, CompileResult>}
     *
     * @overload
     * @param {Plugin<Parameters, Input, Output>} plugin
     * @param {...(Parameters | [boolean])} parameters
     * @returns {UsePlugin<ParseTree, HeadTree, TailTree, CompileTree, CompileResult, Input, Output>}
     *
     * @param {PluggableList | Plugin | Preset | null | undefined} value
     *   Usable value.
     * @param {...unknown} parameters
     *   Parameters, when a plugin is given as a usable value.
     * @returns {Processor<ParseTree, HeadTree, TailTree, CompileTree, CompileResult>}
     *   Current processor.
     */
    use(value, ...parameters) {
      const attachers = this.attachers;
      const namespace = this.namespace;
      assertUnfrozen("use", this.frozen);
      if (value === null || value === void 0) ;
      else if (typeof value === "function") {
        addPlugin(value, parameters);
      } else if (typeof value === "object") {
        if (Array.isArray(value)) {
          addList(value);
        } else {
          addPreset(value);
        }
      } else {
        throw new TypeError("Expected usable value, not `" + value + "`");
      }
      return this;
      function add(value2) {
        if (typeof value2 === "function") {
          addPlugin(value2, []);
        } else if (typeof value2 === "object") {
          if (Array.isArray(value2)) {
            const [plugin, ...parameters2] = (
              /** @type {PluginTuple<Array<unknown>>} */
              value2
            );
            addPlugin(plugin, parameters2);
          } else {
            addPreset(value2);
          }
        } else {
          throw new TypeError("Expected usable value, not `" + value2 + "`");
        }
      }
      function addPreset(result) {
        if (!("plugins" in result) && !("settings" in result)) {
          throw new Error(
            "Expected usable value but received an empty preset, which is probably a mistake: presets typically come with `plugins` and sometimes with `settings`, but this has neither"
          );
        }
        addList(result.plugins);
        if (result.settings) {
          namespace.settings = {
            ...namespace.settings,
            ...structuredClone$1(result.settings)
          };
        }
      }
      function addList(plugins) {
        let index2 = -1;
        if (plugins === null || plugins === void 0) ;
        else if (Array.isArray(plugins)) {
          while (++index2 < plugins.length) {
            const thing = plugins[index2];
            add(thing);
          }
        } else {
          throw new TypeError("Expected a list of plugins, not `" + plugins + "`");
        }
      }
      function addPlugin(plugin, parameters2) {
        let index2 = -1;
        let entryIndex = -1;
        while (++index2 < attachers.length) {
          if (attachers[index2][0] === plugin) {
            entryIndex = index2;
            break;
          }
        }
        if (entryIndex === -1) {
          attachers.push([plugin, ...parameters2]);
        } else if (parameters2.length > 0) {
          let [primary, ...rest] = parameters2;
          const currentPrimary = attachers[entryIndex][1];
          if (isPlainObject(currentPrimary) && isPlainObject(primary)) {
            primary = structuredClone$1({ ...currentPrimary, ...primary });
          }
          attachers[entryIndex] = [plugin, primary, ...rest];
        }
      }
    }
  }
  const unified = new Processor().freeze();
  function assertParser(name2, value) {
    if (typeof value !== "function") {
      throw new TypeError("Cannot `" + name2 + "` without `parser`");
    }
  }
  function assertCompiler(name2, value) {
    if (typeof value !== "function") {
      throw new TypeError("Cannot `" + name2 + "` without `compiler`");
    }
  }
  function assertUnfrozen(name2, frozen) {
    if (frozen) {
      throw new Error(
        "Cannot call `" + name2 + "` on a frozen processor.\nCreate a new processor first, by calling it: use `processor()` instead of `processor`."
      );
    }
  }
  function assertNode(node2) {
    if (!isPlainObject(node2) || typeof node2.type !== "string") {
      throw new TypeError("Expected node, got `" + node2 + "`");
    }
  }
  function assertDone(name2, asyncName, complete) {
    if (!complete) {
      throw new Error(
        "`" + name2 + "` finished async. Use `" + asyncName + "` instead"
      );
    }
  }
  function vfile(value) {
    return looksLikeAVFile(value) ? value : new VFile(value);
  }
  function looksLikeAVFile(value) {
    return Boolean(
      value && typeof value === "object" && "message" in value && "messages" in value
    );
  }
  function looksLikeAValue(value) {
    return typeof value === "string" || isUint8Array(value);
  }
  function isUint8Array(value) {
    return Boolean(
      value && typeof value === "object" && "byteLength" in value && "byteOffset" in value
    );
  }
  const changelog = "https://github.com/remarkjs/react-markdown/blob/main/changelog.md";
  const emptyPlugins = [];
  const emptyRemarkRehypeOptions = { allowDangerousHtml: true };
  const safeProtocol = /^(https?|ircs?|mailto|xmpp)$/i;
  const deprecations = [
    { from: "astPlugins", id: "remove-buggy-html-in-markdown-parser" },
    { from: "allowDangerousHtml", id: "remove-buggy-html-in-markdown-parser" },
    {
      from: "allowNode",
      id: "replace-allownode-allowedtypes-and-disallowedtypes",
      to: "allowElement"
    },
    {
      from: "allowedTypes",
      id: "replace-allownode-allowedtypes-and-disallowedtypes",
      to: "allowedElements"
    },
    {
      from: "disallowedTypes",
      id: "replace-allownode-allowedtypes-and-disallowedtypes",
      to: "disallowedElements"
    },
    { from: "escapeHtml", id: "remove-buggy-html-in-markdown-parser" },
    { from: "includeElementIndex", id: "#remove-includeelementindex" },
    {
      from: "includeNodeIndex",
      id: "change-includenodeindex-to-includeelementindex"
    },
    { from: "linkTarget", id: "remove-linktarget" },
    { from: "plugins", id: "change-plugins-to-remarkplugins", to: "remarkPlugins" },
    { from: "rawSourcePos", id: "#remove-rawsourcepos" },
    { from: "renderers", id: "change-renderers-to-components", to: "components" },
    { from: "source", id: "change-source-to-children", to: "children" },
    { from: "sourcePos", id: "#remove-sourcepos" },
    { from: "transformImageUri", id: "#add-urltransform", to: "urlTransform" },
    { from: "transformLinkUri", id: "#add-urltransform", to: "urlTransform" }
  ];
  function Markdown$1(options) {
    const processor = createProcessor(options);
    const file = createFile(options);
    return post(processor.runSync(processor.parse(file), file), options);
  }
  function createProcessor(options) {
    const rehypePlugins = options.rehypePlugins || emptyPlugins;
    const remarkPlugins = options.remarkPlugins || emptyPlugins;
    const remarkRehypeOptions = options.remarkRehypeOptions ? { ...options.remarkRehypeOptions, ...emptyRemarkRehypeOptions } : emptyRemarkRehypeOptions;
    const processor = unified().use(remarkParse).use(remarkPlugins).use(remarkRehype, remarkRehypeOptions).use(rehypePlugins);
    return processor;
  }
  function createFile(options) {
    const children = options.children || "";
    const file = new VFile();
    if (typeof children === "string") {
      file.value = children;
    }
    return file;
  }
  function post(tree, options) {
    const allowedElements = options.allowedElements;
    const allowElement = options.allowElement;
    const components = options.components;
    const disallowedElements = options.disallowedElements;
    const skipHtml = options.skipHtml;
    const unwrapDisallowed = options.unwrapDisallowed;
    const urlTransform = options.urlTransform || defaultUrlTransform;
    for (const deprecation of deprecations) {
      if (Object.hasOwn(options, deprecation.from)) {
        unreachable(
          "Unexpected `" + deprecation.from + "` prop, " + (deprecation.to ? "use `" + deprecation.to + "` instead" : "remove it") + " (see <" + changelog + "#" + deprecation.id + "> for more info)"
        );
      }
    }
    if (options.className) {
      tree = {
        type: "element",
        tagName: "div",
        properties: { className: options.className },
        // Assume no doctypes.
        children: (
          /** @type {Array<ElementContent>} */
          tree.type === "root" ? tree.children : [tree]
        )
      };
    }
    visit(tree, transform);
    return toJsxRuntime(tree, {
      Fragment: jsxRuntimeExports.Fragment,
      // @ts-expect-error
      // React components are allowed to return numbers,
      // but not according to the types in hast-util-to-jsx-runtime
      components,
      ignoreInvalidStyle: true,
      jsx: jsxRuntimeExports.jsx,
      jsxs: jsxRuntimeExports.jsxs,
      passKeys: true,
      passNode: true
    });
    function transform(node2, index2, parent) {
      if (node2.type === "raw" && parent && typeof index2 === "number") {
        if (skipHtml) {
          parent.children.splice(index2, 1);
        } else {
          parent.children[index2] = { type: "text", value: node2.value };
        }
        return index2;
      }
      if (node2.type === "element") {
        let key;
        for (key in urlAttributes) {
          if (Object.hasOwn(urlAttributes, key) && Object.hasOwn(node2.properties, key)) {
            const value = node2.properties[key];
            const test = urlAttributes[key];
            if (test === null || test.includes(node2.tagName)) {
              node2.properties[key] = urlTransform(String(value || ""), key, node2);
            }
          }
        }
      }
      if (node2.type === "element") {
        let remove = allowedElements ? !allowedElements.includes(node2.tagName) : disallowedElements ? disallowedElements.includes(node2.tagName) : false;
        if (!remove && allowElement && typeof index2 === "number") {
          remove = !allowElement(node2, index2, parent);
        }
        if (remove && parent && typeof index2 === "number") {
          if (unwrapDisallowed && node2.children) {
            parent.children.splice(index2, 1, ...node2.children);
          } else {
            parent.children.splice(index2, 1);
          }
          return index2;
        }
      }
    }
  }
  function defaultUrlTransform(value) {
    const colon = value.indexOf(":");
    const questionMark = value.indexOf("?");
    const numberSign = value.indexOf("#");
    const slash = value.indexOf("/");
    if (
      // If there is no protocol, it’s relative.
      colon === -1 || // If the first colon is after a `?`, `#`, or `/`, it’s not a protocol.
      slash !== -1 && colon > slash || questionMark !== -1 && colon > questionMark || numberSign !== -1 && colon > numberSign || // It is a protocol, it should be allowed.
      safeProtocol.test(value.slice(0, colon))
    ) {
      return value;
    }
    return "";
  }
  function ccount(value, character) {
    const source = String(value);
    if (typeof character !== "string") {
      throw new TypeError("Expected character");
    }
    let count = 0;
    let index2 = source.indexOf(character);
    while (index2 !== -1) {
      count++;
      index2 = source.indexOf(character, index2 + character.length);
    }
    return count;
  }
  function escapeStringRegexp(string2) {
    if (typeof string2 !== "string") {
      throw new TypeError("Expected a string");
    }
    return string2.replace(/[|\\{}()[\]^$+*?.]/g, "\\$&").replace(/-/g, "\\x2d");
  }
  function findAndReplace(tree, list2, options) {
    const settings = options || {};
    const ignored = convert(settings.ignore || []);
    const pairs = toPairs(list2);
    let pairIndex = -1;
    while (++pairIndex < pairs.length) {
      visitParents(tree, "text", visitor);
    }
    function visitor(node2, parents) {
      let index2 = -1;
      let grandparent;
      while (++index2 < parents.length) {
        const parent = parents[index2];
        const siblings = grandparent ? grandparent.children : void 0;
        if (ignored(
          parent,
          siblings ? siblings.indexOf(parent) : void 0,
          grandparent
        )) {
          return;
        }
        grandparent = parent;
      }
      if (grandparent) {
        return handler(node2, parents);
      }
    }
    function handler(node2, parents) {
      const parent = parents[parents.length - 1];
      const find2 = pairs[pairIndex][0];
      const replace2 = pairs[pairIndex][1];
      let start = 0;
      const siblings = parent.children;
      const index2 = siblings.indexOf(node2);
      let change = false;
      let nodes = [];
      find2.lastIndex = 0;
      let match = find2.exec(node2.value);
      while (match) {
        const position2 = match.index;
        const matchObject = {
          index: match.index,
          input: match.input,
          stack: [...parents, node2]
        };
        let value = replace2(...match, matchObject);
        if (typeof value === "string") {
          value = value.length > 0 ? { type: "text", value } : void 0;
        }
        if (value === false) {
          find2.lastIndex = position2 + 1;
        } else {
          if (start !== position2) {
            nodes.push({
              type: "text",
              value: node2.value.slice(start, position2)
            });
          }
          if (Array.isArray(value)) {
            nodes.push(...value);
          } else if (value) {
            nodes.push(value);
          }
          start = position2 + match[0].length;
          change = true;
        }
        if (!find2.global) {
          break;
        }
        match = find2.exec(node2.value);
      }
      if (change) {
        if (start < node2.value.length) {
          nodes.push({ type: "text", value: node2.value.slice(start) });
        }
        parent.children.splice(index2, 1, ...nodes);
      } else {
        nodes = [node2];
      }
      return index2 + nodes.length;
    }
  }
  function toPairs(tupleOrList) {
    const result = [];
    if (!Array.isArray(tupleOrList)) {
      throw new TypeError("Expected find and replace tuple or list of tuples");
    }
    const list2 = !tupleOrList[0] || Array.isArray(tupleOrList[0]) ? tupleOrList : [tupleOrList];
    let index2 = -1;
    while (++index2 < list2.length) {
      const tuple = list2[index2];
      result.push([toExpression(tuple[0]), toFunction(tuple[1])]);
    }
    return result;
  }
  function toExpression(find2) {
    return typeof find2 === "string" ? new RegExp(escapeStringRegexp(find2), "g") : find2;
  }
  function toFunction(replace2) {
    return typeof replace2 === "function" ? replace2 : function() {
      return replace2;
    };
  }
  const inConstruct = "phrasing";
  const notInConstruct = ["autolink", "link", "image", "label"];
  function gfmAutolinkLiteralFromMarkdown() {
    return {
      transforms: [transformGfmAutolinkLiterals],
      enter: {
        literalAutolink: enterLiteralAutolink,
        literalAutolinkEmail: enterLiteralAutolinkValue,
        literalAutolinkHttp: enterLiteralAutolinkValue,
        literalAutolinkWww: enterLiteralAutolinkValue
      },
      exit: {
        literalAutolink: exitLiteralAutolink,
        literalAutolinkEmail: exitLiteralAutolinkEmail,
        literalAutolinkHttp: exitLiteralAutolinkHttp,
        literalAutolinkWww: exitLiteralAutolinkWww
      }
    };
  }
  function gfmAutolinkLiteralToMarkdown() {
    return {
      unsafe: [
        {
          character: "@",
          before: "[+\\-.\\w]",
          after: "[\\-.\\w]",
          inConstruct,
          notInConstruct
        },
        {
          character: ".",
          before: "[Ww]",
          after: "[\\-.\\w]",
          inConstruct,
          notInConstruct
        },
        {
          character: ":",
          before: "[ps]",
          after: "\\/",
          inConstruct,
          notInConstruct
        }
      ]
    };
  }
  function enterLiteralAutolink(token) {
    this.enter({ type: "link", title: null, url: "", children: [] }, token);
  }
  function enterLiteralAutolinkValue(token) {
    this.config.enter.autolinkProtocol.call(this, token);
  }
  function exitLiteralAutolinkHttp(token) {
    this.config.exit.autolinkProtocol.call(this, token);
  }
  function exitLiteralAutolinkWww(token) {
    this.config.exit.data.call(this, token);
    const node2 = this.stack[this.stack.length - 1];
    ok$1(node2.type === "link");
    node2.url = "http://" + this.sliceSerialize(token);
  }
  function exitLiteralAutolinkEmail(token) {
    this.config.exit.autolinkEmail.call(this, token);
  }
  function exitLiteralAutolink(token) {
    this.exit(token);
  }
  function transformGfmAutolinkLiterals(tree) {
    findAndReplace(
      tree,
      [
        [/(https?:\/\/|www(?=\.))([-.\w]+)([^ \t\r\n]*)/gi, findUrl],
        [new RegExp("(?<=^|\\s|\\p{P}|\\p{S})([-.\\w+]+)@([-\\w]+(?:\\.[-\\w]+)+)", "gu"), findEmail]
      ],
      { ignore: ["link", "linkReference"] }
    );
  }
  function findUrl(_, protocol, domain2, path2, match) {
    let prefix = "";
    if (!previous(match)) {
      return false;
    }
    if (/^w/i.test(protocol)) {
      domain2 = protocol + domain2;
      protocol = "";
      prefix = "http://";
    }
    if (!isCorrectDomain(domain2)) {
      return false;
    }
    const parts = splitUrl(domain2 + path2);
    if (!parts[0]) return false;
    const result = {
      type: "link",
      title: null,
      url: prefix + protocol + parts[0],
      children: [{ type: "text", value: protocol + parts[0] }]
    };
    if (parts[1]) {
      return [result, { type: "text", value: parts[1] }];
    }
    return result;
  }
  function findEmail(_, atext, label, match) {
    if (
      // Not an expected previous character.
      !previous(match, true) || // Label ends in not allowed character.
      /[-\d_]$/.test(label)
    ) {
      return false;
    }
    return {
      type: "link",
      title: null,
      url: "mailto:" + atext + "@" + label,
      children: [{ type: "text", value: atext + "@" + label }]
    };
  }
  function isCorrectDomain(domain2) {
    const parts = domain2.split(".");
    if (parts.length < 2 || parts[parts.length - 1] && (/_/.test(parts[parts.length - 1]) || !/[a-zA-Z\d]/.test(parts[parts.length - 1])) || parts[parts.length - 2] && (/_/.test(parts[parts.length - 2]) || !/[a-zA-Z\d]/.test(parts[parts.length - 2]))) {
      return false;
    }
    return true;
  }
  function splitUrl(url) {
    const trailExec = /[!"&'),.:;<>?\]}]+$/.exec(url);
    if (!trailExec) {
      return [url, void 0];
    }
    url = url.slice(0, trailExec.index);
    let trail2 = trailExec[0];
    let closingParenIndex = trail2.indexOf(")");
    const openingParens = ccount(url, "(");
    let closingParens = ccount(url, ")");
    while (closingParenIndex !== -1 && openingParens > closingParens) {
      url += trail2.slice(0, closingParenIndex + 1);
      trail2 = trail2.slice(closingParenIndex + 1);
      closingParenIndex = trail2.indexOf(")");
      closingParens++;
    }
    return [url, trail2];
  }
  function previous(match, email) {
    const code2 = match.input.charCodeAt(match.index - 1);
    return (match.index === 0 || unicodeWhitespace(code2) || unicodePunctuation(code2)) && // If it’s an email, the previous character should not be a slash.
    (!email || code2 !== 47);
  }
  footnoteReference.peek = footnoteReferencePeek;
  function enterFootnoteCallString() {
    this.buffer();
  }
  function enterFootnoteCall(token) {
    this.enter({ type: "footnoteReference", identifier: "", label: "" }, token);
  }
  function enterFootnoteDefinitionLabelString() {
    this.buffer();
  }
  function enterFootnoteDefinition(token) {
    this.enter(
      { type: "footnoteDefinition", identifier: "", label: "", children: [] },
      token
    );
  }
  function exitFootnoteCallString(token) {
    const label = this.resume();
    const node2 = this.stack[this.stack.length - 1];
    ok$1(node2.type === "footnoteReference");
    node2.identifier = normalizeIdentifier(
      this.sliceSerialize(token)
    ).toLowerCase();
    node2.label = label;
  }
  function exitFootnoteCall(token) {
    this.exit(token);
  }
  function exitFootnoteDefinitionLabelString(token) {
    const label = this.resume();
    const node2 = this.stack[this.stack.length - 1];
    ok$1(node2.type === "footnoteDefinition");
    node2.identifier = normalizeIdentifier(
      this.sliceSerialize(token)
    ).toLowerCase();
    node2.label = label;
  }
  function exitFootnoteDefinition(token) {
    this.exit(token);
  }
  function footnoteReferencePeek() {
    return "[";
  }
  function footnoteReference(node2, _, state, info) {
    const tracker = state.createTracker(info);
    let value = tracker.move("[^");
    const exit2 = state.enter("footnoteReference");
    const subexit = state.enter("reference");
    value += tracker.move(
      state.safe(state.associationId(node2), { after: "]", before: value })
    );
    subexit();
    exit2();
    value += tracker.move("]");
    return value;
  }
  function gfmFootnoteFromMarkdown() {
    return {
      enter: {
        gfmFootnoteCallString: enterFootnoteCallString,
        gfmFootnoteCall: enterFootnoteCall,
        gfmFootnoteDefinitionLabelString: enterFootnoteDefinitionLabelString,
        gfmFootnoteDefinition: enterFootnoteDefinition
      },
      exit: {
        gfmFootnoteCallString: exitFootnoteCallString,
        gfmFootnoteCall: exitFootnoteCall,
        gfmFootnoteDefinitionLabelString: exitFootnoteDefinitionLabelString,
        gfmFootnoteDefinition: exitFootnoteDefinition
      }
    };
  }
  function gfmFootnoteToMarkdown(options) {
    let firstLineBlank = false;
    if (options && options.firstLineBlank) {
      firstLineBlank = true;
    }
    return {
      handlers: { footnoteDefinition, footnoteReference },
      // This is on by default already.
      unsafe: [{ character: "[", inConstruct: ["label", "phrasing", "reference"] }]
    };
    function footnoteDefinition(node2, _, state, info) {
      const tracker = state.createTracker(info);
      let value = tracker.move("[^");
      const exit2 = state.enter("footnoteDefinition");
      const subexit = state.enter("label");
      value += tracker.move(
        state.safe(state.associationId(node2), { before: value, after: "]" })
      );
      subexit();
      value += tracker.move("]:");
      if (node2.children && node2.children.length > 0) {
        tracker.shift(4);
        value += tracker.move(
          (firstLineBlank ? "\n" : " ") + state.indentLines(
            state.containerFlow(node2, tracker.current()),
            firstLineBlank ? mapAll : mapExceptFirst
          )
        );
      }
      exit2();
      return value;
    }
  }
  function mapExceptFirst(line, index2, blank) {
    return index2 === 0 ? line : mapAll(line, index2, blank);
  }
  function mapAll(line, index2, blank) {
    return (blank ? "" : "    ") + line;
  }
  const constructsWithoutStrikethrough = [
    "autolink",
    "destinationLiteral",
    "destinationRaw",
    "reference",
    "titleQuote",
    "titleApostrophe"
  ];
  handleDelete.peek = peekDelete;
  function gfmStrikethroughFromMarkdown() {
    return {
      canContainEols: ["delete"],
      enter: { strikethrough: enterStrikethrough },
      exit: { strikethrough: exitStrikethrough }
    };
  }
  function gfmStrikethroughToMarkdown() {
    return {
      unsafe: [
        {
          character: "~",
          inConstruct: "phrasing",
          notInConstruct: constructsWithoutStrikethrough
        }
      ],
      handlers: { delete: handleDelete }
    };
  }
  function enterStrikethrough(token) {
    this.enter({ type: "delete", children: [] }, token);
  }
  function exitStrikethrough(token) {
    this.exit(token);
  }
  function handleDelete(node2, _, state, info) {
    const tracker = state.createTracker(info);
    const exit2 = state.enter("strikethrough");
    let value = tracker.move("~~");
    value += state.containerPhrasing(node2, {
      ...tracker.current(),
      before: value,
      after: "~"
    });
    value += tracker.move("~~");
    exit2();
    return value;
  }
  function peekDelete() {
    return "~";
  }
  function defaultStringLength(value) {
    return value.length;
  }
  function markdownTable(table2, options) {
    const settings = options || {};
    const align = (settings.align || []).concat();
    const stringLength = settings.stringLength || defaultStringLength;
    const alignments = [];
    const cellMatrix = [];
    const sizeMatrix = [];
    const longestCellByColumn = [];
    let mostCellsPerRow = 0;
    let rowIndex = -1;
    while (++rowIndex < table2.length) {
      const row2 = [];
      const sizes2 = [];
      let columnIndex2 = -1;
      if (table2[rowIndex].length > mostCellsPerRow) {
        mostCellsPerRow = table2[rowIndex].length;
      }
      while (++columnIndex2 < table2[rowIndex].length) {
        const cell = serialize(table2[rowIndex][columnIndex2]);
        if (settings.alignDelimiters !== false) {
          const size = stringLength(cell);
          sizes2[columnIndex2] = size;
          if (longestCellByColumn[columnIndex2] === void 0 || size > longestCellByColumn[columnIndex2]) {
            longestCellByColumn[columnIndex2] = size;
          }
        }
        row2.push(cell);
      }
      cellMatrix[rowIndex] = row2;
      sizeMatrix[rowIndex] = sizes2;
    }
    let columnIndex = -1;
    if (typeof align === "object" && "length" in align) {
      while (++columnIndex < mostCellsPerRow) {
        alignments[columnIndex] = toAlignment(align[columnIndex]);
      }
    } else {
      const code2 = toAlignment(align);
      while (++columnIndex < mostCellsPerRow) {
        alignments[columnIndex] = code2;
      }
    }
    columnIndex = -1;
    const row = [];
    const sizes = [];
    while (++columnIndex < mostCellsPerRow) {
      const code2 = alignments[columnIndex];
      let before = "";
      let after = "";
      if (code2 === 99) {
        before = ":";
        after = ":";
      } else if (code2 === 108) {
        before = ":";
      } else if (code2 === 114) {
        after = ":";
      }
      let size = settings.alignDelimiters === false ? 1 : Math.max(
        1,
        longestCellByColumn[columnIndex] - before.length - after.length
      );
      const cell = before + "-".repeat(size) + after;
      if (settings.alignDelimiters !== false) {
        size = before.length + size + after.length;
        if (size > longestCellByColumn[columnIndex]) {
          longestCellByColumn[columnIndex] = size;
        }
        sizes[columnIndex] = size;
      }
      row[columnIndex] = cell;
    }
    cellMatrix.splice(1, 0, row);
    sizeMatrix.splice(1, 0, sizes);
    rowIndex = -1;
    const lines = [];
    while (++rowIndex < cellMatrix.length) {
      const row2 = cellMatrix[rowIndex];
      const sizes2 = sizeMatrix[rowIndex];
      columnIndex = -1;
      const line = [];
      while (++columnIndex < mostCellsPerRow) {
        const cell = row2[columnIndex] || "";
        let before = "";
        let after = "";
        if (settings.alignDelimiters !== false) {
          const size = longestCellByColumn[columnIndex] - (sizes2[columnIndex] || 0);
          const code2 = alignments[columnIndex];
          if (code2 === 114) {
            before = " ".repeat(size);
          } else if (code2 === 99) {
            if (size % 2) {
              before = " ".repeat(size / 2 + 0.5);
              after = " ".repeat(size / 2 - 0.5);
            } else {
              before = " ".repeat(size / 2);
              after = before;
            }
          } else {
            after = " ".repeat(size);
          }
        }
        if (settings.delimiterStart !== false && !columnIndex) {
          line.push("|");
        }
        if (settings.padding !== false && // Don’t add the opening space if we’re not aligning and the cell is
        // empty: there will be a closing space.
        !(settings.alignDelimiters === false && cell === "") && (settings.delimiterStart !== false || columnIndex)) {
          line.push(" ");
        }
        if (settings.alignDelimiters !== false) {
          line.push(before);
        }
        line.push(cell);
        if (settings.alignDelimiters !== false) {
          line.push(after);
        }
        if (settings.padding !== false) {
          line.push(" ");
        }
        if (settings.delimiterEnd !== false || columnIndex !== mostCellsPerRow - 1) {
          line.push("|");
        }
      }
      lines.push(
        settings.delimiterEnd === false ? line.join("").replace(/ +$/, "") : line.join("")
      );
    }
    return lines.join("\n");
  }
  function serialize(value) {
    return value === null || value === void 0 ? "" : String(value);
  }
  function toAlignment(value) {
    const code2 = typeof value === "string" ? value.codePointAt(0) : 0;
    return code2 === 67 || code2 === 99 ? 99 : code2 === 76 || code2 === 108 ? 108 : code2 === 82 || code2 === 114 ? 114 : 0;
  }
  function blockquote(node2, _, state, info) {
    const exit2 = state.enter("blockquote");
    const tracker = state.createTracker(info);
    tracker.move("> ");
    tracker.shift(2);
    const value = state.indentLines(
      state.containerFlow(node2, tracker.current()),
      map$1
    );
    exit2();
    return value;
  }
  function map$1(line, _, blank) {
    return ">" + (blank ? "" : " ") + line;
  }
  function patternInScope(stack, pattern) {
    return listInScope(stack, pattern.inConstruct, true) && !listInScope(stack, pattern.notInConstruct, false);
  }
  function listInScope(stack, list2, none) {
    if (typeof list2 === "string") {
      list2 = [list2];
    }
    if (!list2 || list2.length === 0) {
      return none;
    }
    let index2 = -1;
    while (++index2 < list2.length) {
      if (stack.includes(list2[index2])) {
        return true;
      }
    }
    return false;
  }
  function hardBreak(_, _1, state, info) {
    let index2 = -1;
    while (++index2 < state.unsafe.length) {
      if (state.unsafe[index2].character === "\n" && patternInScope(state.stack, state.unsafe[index2])) {
        return /[ \t]/.test(info.before) ? "" : " ";
      }
    }
    return "\\\n";
  }
  function longestStreak(value, substring) {
    const source = String(value);
    let index2 = source.indexOf(substring);
    let expected = index2;
    let count = 0;
    let max = 0;
    if (typeof substring !== "string") {
      throw new TypeError("Expected substring");
    }
    while (index2 !== -1) {
      if (index2 === expected) {
        if (++count > max) {
          max = count;
        }
      } else {
        count = 1;
      }
      expected = index2 + substring.length;
      index2 = source.indexOf(substring, expected);
    }
    return max;
  }
  function formatCodeAsIndented(node2, state) {
    return Boolean(
      state.options.fences === false && node2.value && // If there’s no info…
      !node2.lang && // And there’s a non-whitespace character…
      /[^ \r\n]/.test(node2.value) && // And the value doesn’t start or end in a blank…
      !/^[\t ]*(?:[\r\n]|$)|(?:^|[\r\n])[\t ]*$/.test(node2.value)
    );
  }
  function checkFence(state) {
    const marker = state.options.fence || "`";
    if (marker !== "`" && marker !== "~") {
      throw new Error(
        "Cannot serialize code with `" + marker + "` for `options.fence`, expected `` ` `` or `~`"
      );
    }
    return marker;
  }
  function code$1(node2, _, state, info) {
    const marker = checkFence(state);
    const raw = node2.value || "";
    const suffix = marker === "`" ? "GraveAccent" : "Tilde";
    if (formatCodeAsIndented(node2, state)) {
      const exit3 = state.enter("codeIndented");
      const value2 = state.indentLines(raw, map);
      exit3();
      return value2;
    }
    const tracker = state.createTracker(info);
    const sequence = marker.repeat(Math.max(longestStreak(raw, marker) + 1, 3));
    const exit2 = state.enter("codeFenced");
    let value = tracker.move(sequence);
    if (node2.lang) {
      const subexit = state.enter(`codeFencedLang${suffix}`);
      value += tracker.move(
        state.safe(node2.lang, {
          before: value,
          after: " ",
          encode: ["`"],
          ...tracker.current()
        })
      );
      subexit();
    }
    if (node2.lang && node2.meta) {
      const subexit = state.enter(`codeFencedMeta${suffix}`);
      value += tracker.move(" ");
      value += tracker.move(
        state.safe(node2.meta, {
          before: value,
          after: "\n",
          encode: ["`"],
          ...tracker.current()
        })
      );
      subexit();
    }
    value += tracker.move("\n");
    if (raw) {
      value += tracker.move(raw + "\n");
    }
    value += tracker.move(sequence);
    exit2();
    return value;
  }
  function map(line, _, blank) {
    return (blank ? "" : "    ") + line;
  }
  function checkQuote(state) {
    const marker = state.options.quote || '"';
    if (marker !== '"' && marker !== "'") {
      throw new Error(
        "Cannot serialize title with `" + marker + "` for `options.quote`, expected `\"`, or `'`"
      );
    }
    return marker;
  }
  function definition(node2, _, state, info) {
    const quote = checkQuote(state);
    const suffix = quote === '"' ? "Quote" : "Apostrophe";
    const exit2 = state.enter("definition");
    let subexit = state.enter("label");
    const tracker = state.createTracker(info);
    let value = tracker.move("[");
    value += tracker.move(
      state.safe(state.associationId(node2), {
        before: value,
        after: "]",
        ...tracker.current()
      })
    );
    value += tracker.move("]: ");
    subexit();
    if (
      // If there’s no url, or…
      !node2.url || // If there are control characters or whitespace.
      /[\0- \u007F]/.test(node2.url)
    ) {
      subexit = state.enter("destinationLiteral");
      value += tracker.move("<");
      value += tracker.move(
        state.safe(node2.url, { before: value, after: ">", ...tracker.current() })
      );
      value += tracker.move(">");
    } else {
      subexit = state.enter("destinationRaw");
      value += tracker.move(
        state.safe(node2.url, {
          before: value,
          after: node2.title ? " " : "\n",
          ...tracker.current()
        })
      );
    }
    subexit();
    if (node2.title) {
      subexit = state.enter(`title${suffix}`);
      value += tracker.move(" " + quote);
      value += tracker.move(
        state.safe(node2.title, {
          before: value,
          after: quote,
          ...tracker.current()
        })
      );
      value += tracker.move(quote);
      subexit();
    }
    exit2();
    return value;
  }
  function checkEmphasis(state) {
    const marker = state.options.emphasis || "*";
    if (marker !== "*" && marker !== "_") {
      throw new Error(
        "Cannot serialize emphasis with `" + marker + "` for `options.emphasis`, expected `*`, or `_`"
      );
    }
    return marker;
  }
  emphasis.peek = emphasisPeek;
  function emphasis(node2, _, state, info) {
    const marker = checkEmphasis(state);
    const exit2 = state.enter("emphasis");
    const tracker = state.createTracker(info);
    let value = tracker.move(marker);
    value += tracker.move(
      state.containerPhrasing(node2, {
        before: value,
        after: marker,
        ...tracker.current()
      })
    );
    value += tracker.move(marker);
    exit2();
    return value;
  }
  function emphasisPeek(_, _1, state) {
    return state.options.emphasis || "*";
  }
  function formatHeadingAsSetext(node2, state) {
    let literalWithBreak = false;
    visit(node2, function(node3) {
      if ("value" in node3 && /\r?\n|\r/.test(node3.value) || node3.type === "break") {
        literalWithBreak = true;
        return EXIT;
      }
    });
    return Boolean(
      (!node2.depth || node2.depth < 3) && toString$1(node2) && (state.options.setext || literalWithBreak)
    );
  }
  function heading(node2, _, state, info) {
    const rank = Math.max(Math.min(6, node2.depth || 1), 1);
    const tracker = state.createTracker(info);
    if (formatHeadingAsSetext(node2, state)) {
      const exit3 = state.enter("headingSetext");
      const subexit2 = state.enter("phrasing");
      const value2 = state.containerPhrasing(node2, {
        ...tracker.current(),
        before: "\n",
        after: "\n"
      });
      subexit2();
      exit3();
      return value2 + "\n" + (rank === 1 ? "=" : "-").repeat(
        // The whole size…
        value2.length - // Minus the position of the character after the last EOL (or
        // 0 if there is none)…
        (Math.max(value2.lastIndexOf("\r"), value2.lastIndexOf("\n")) + 1)
      );
    }
    const sequence = "#".repeat(rank);
    const exit2 = state.enter("headingAtx");
    const subexit = state.enter("phrasing");
    tracker.move(sequence + " ");
    let value = state.containerPhrasing(node2, {
      before: "# ",
      after: "\n",
      ...tracker.current()
    });
    if (/^[\t ]/.test(value)) {
      value = "&#x" + value.charCodeAt(0).toString(16).toUpperCase() + ";" + value.slice(1);
    }
    value = value ? sequence + " " + value : sequence;
    if (state.options.closeAtx) {
      value += " " + sequence;
    }
    subexit();
    exit2();
    return value;
  }
  html.peek = htmlPeek;
  function html(node2) {
    return node2.value || "";
  }
  function htmlPeek() {
    return "<";
  }
  image.peek = imagePeek;
  function image(node2, _, state, info) {
    const quote = checkQuote(state);
    const suffix = quote === '"' ? "Quote" : "Apostrophe";
    const exit2 = state.enter("image");
    let subexit = state.enter("label");
    const tracker = state.createTracker(info);
    let value = tracker.move("![");
    value += tracker.move(
      state.safe(node2.alt, { before: value, after: "]", ...tracker.current() })
    );
    value += tracker.move("](");
    subexit();
    if (
      // If there’s no url but there is a title…
      !node2.url && node2.title || // If there are control characters or whitespace.
      /[\0- \u007F]/.test(node2.url)
    ) {
      subexit = state.enter("destinationLiteral");
      value += tracker.move("<");
      value += tracker.move(
        state.safe(node2.url, { before: value, after: ">", ...tracker.current() })
      );
      value += tracker.move(">");
    } else {
      subexit = state.enter("destinationRaw");
      value += tracker.move(
        state.safe(node2.url, {
          before: value,
          after: node2.title ? " " : ")",
          ...tracker.current()
        })
      );
    }
    subexit();
    if (node2.title) {
      subexit = state.enter(`title${suffix}`);
      value += tracker.move(" " + quote);
      value += tracker.move(
        state.safe(node2.title, {
          before: value,
          after: quote,
          ...tracker.current()
        })
      );
      value += tracker.move(quote);
      subexit();
    }
    value += tracker.move(")");
    exit2();
    return value;
  }
  function imagePeek() {
    return "!";
  }
  imageReference.peek = imageReferencePeek;
  function imageReference(node2, _, state, info) {
    const type = node2.referenceType;
    const exit2 = state.enter("imageReference");
    let subexit = state.enter("label");
    const tracker = state.createTracker(info);
    let value = tracker.move("![");
    const alt = state.safe(node2.alt, {
      before: value,
      after: "]",
      ...tracker.current()
    });
    value += tracker.move(alt + "][");
    subexit();
    const stack = state.stack;
    state.stack = [];
    subexit = state.enter("reference");
    const reference = state.safe(state.associationId(node2), {
      before: value,
      after: "]",
      ...tracker.current()
    });
    subexit();
    state.stack = stack;
    exit2();
    if (type === "full" || !alt || alt !== reference) {
      value += tracker.move(reference + "]");
    } else if (type === "shortcut") {
      value = value.slice(0, -1);
    } else {
      value += tracker.move("]");
    }
    return value;
  }
  function imageReferencePeek() {
    return "!";
  }
  function patternCompile(pattern) {
    if (!pattern._compiled) {
      const before = (pattern.atBreak ? "[\\r\\n][\\t ]*" : "") + (pattern.before ? "(?:" + pattern.before + ")" : "");
      pattern._compiled = new RegExp(
        (before ? "(" + before + ")" : "") + (/[|\\{}()[\]^$+*?.-]/.test(pattern.character) ? "\\" : "") + pattern.character + (pattern.after ? "(?:" + pattern.after + ")" : ""),
        "g"
      );
    }
    return pattern._compiled;
  }
  inlineCode.peek = inlineCodePeek;
  function inlineCode(node2, _, state) {
    let value = node2.value || "";
    let sequence = "`";
    let index2 = -1;
    while (new RegExp("(^|[^`])" + sequence + "([^`]|$)").test(value)) {
      sequence += "`";
    }
    if (/[^ \r\n]/.test(value) && (/^[ \r\n]/.test(value) && /[ \r\n]$/.test(value) || /^`|`$/.test(value))) {
      value = " " + value + " ";
    }
    while (++index2 < state.unsafe.length) {
      const pattern = state.unsafe[index2];
      const expression = patternCompile(pattern);
      let match;
      if (!pattern.atBreak) continue;
      while (match = expression.exec(value)) {
        let position2 = match.index;
        if (value.charCodeAt(position2) === 10 && value.charCodeAt(position2 - 1) === 13) {
          position2--;
        }
        value = value.slice(0, position2) + " " + value.slice(match.index + 1);
      }
    }
    return sequence + value + sequence;
  }
  function inlineCodePeek() {
    return "`";
  }
  function formatLinkAsAutolink(node2, state) {
    const raw = toString$1(node2);
    return Boolean(
      !state.options.resourceLink && // If there’s a url…
      node2.url && // And there’s a no title…
      !node2.title && // And the content of `node` is a single text node…
      node2.children && node2.children.length === 1 && node2.children[0].type === "text" && // And if the url is the same as the content…
      (raw === node2.url || "mailto:" + raw === node2.url) && // And that starts w/ a protocol…
      /^[a-z][a-z+.-]+:/i.test(node2.url) && // And that doesn’t contain ASCII control codes (character escapes and
      // references don’t work), space, or angle brackets…
      !/[\0- <>\u007F]/.test(node2.url)
    );
  }
  link.peek = linkPeek;
  function link(node2, _, state, info) {
    const quote = checkQuote(state);
    const suffix = quote === '"' ? "Quote" : "Apostrophe";
    const tracker = state.createTracker(info);
    let exit2;
    let subexit;
    if (formatLinkAsAutolink(node2, state)) {
      const stack = state.stack;
      state.stack = [];
      exit2 = state.enter("autolink");
      let value2 = tracker.move("<");
      value2 += tracker.move(
        state.containerPhrasing(node2, {
          before: value2,
          after: ">",
          ...tracker.current()
        })
      );
      value2 += tracker.move(">");
      exit2();
      state.stack = stack;
      return value2;
    }
    exit2 = state.enter("link");
    subexit = state.enter("label");
    let value = tracker.move("[");
    value += tracker.move(
      state.containerPhrasing(node2, {
        before: value,
        after: "](",
        ...tracker.current()
      })
    );
    value += tracker.move("](");
    subexit();
    if (
      // If there’s no url but there is a title…
      !node2.url && node2.title || // If there are control characters or whitespace.
      /[\0- \u007F]/.test(node2.url)
    ) {
      subexit = state.enter("destinationLiteral");
      value += tracker.move("<");
      value += tracker.move(
        state.safe(node2.url, { before: value, after: ">", ...tracker.current() })
      );
      value += tracker.move(">");
    } else {
      subexit = state.enter("destinationRaw");
      value += tracker.move(
        state.safe(node2.url, {
          before: value,
          after: node2.title ? " " : ")",
          ...tracker.current()
        })
      );
    }
    subexit();
    if (node2.title) {
      subexit = state.enter(`title${suffix}`);
      value += tracker.move(" " + quote);
      value += tracker.move(
        state.safe(node2.title, {
          before: value,
          after: quote,
          ...tracker.current()
        })
      );
      value += tracker.move(quote);
      subexit();
    }
    value += tracker.move(")");
    exit2();
    return value;
  }
  function linkPeek(node2, _, state) {
    return formatLinkAsAutolink(node2, state) ? "<" : "[";
  }
  linkReference.peek = linkReferencePeek;
  function linkReference(node2, _, state, info) {
    const type = node2.referenceType;
    const exit2 = state.enter("linkReference");
    let subexit = state.enter("label");
    const tracker = state.createTracker(info);
    let value = tracker.move("[");
    const text2 = state.containerPhrasing(node2, {
      before: value,
      after: "]",
      ...tracker.current()
    });
    value += tracker.move(text2 + "][");
    subexit();
    const stack = state.stack;
    state.stack = [];
    subexit = state.enter("reference");
    const reference = state.safe(state.associationId(node2), {
      before: value,
      after: "]",
      ...tracker.current()
    });
    subexit();
    state.stack = stack;
    exit2();
    if (type === "full" || !text2 || text2 !== reference) {
      value += tracker.move(reference + "]");
    } else if (type === "shortcut") {
      value = value.slice(0, -1);
    } else {
      value += tracker.move("]");
    }
    return value;
  }
  function linkReferencePeek() {
    return "[";
  }
  function checkBullet(state) {
    const marker = state.options.bullet || "*";
    if (marker !== "*" && marker !== "+" && marker !== "-") {
      throw new Error(
        "Cannot serialize items with `" + marker + "` for `options.bullet`, expected `*`, `+`, or `-`"
      );
    }
    return marker;
  }
  function checkBulletOther(state) {
    const bullet = checkBullet(state);
    const bulletOther = state.options.bulletOther;
    if (!bulletOther) {
      return bullet === "*" ? "-" : "*";
    }
    if (bulletOther !== "*" && bulletOther !== "+" && bulletOther !== "-") {
      throw new Error(
        "Cannot serialize items with `" + bulletOther + "` for `options.bulletOther`, expected `*`, `+`, or `-`"
      );
    }
    if (bulletOther === bullet) {
      throw new Error(
        "Expected `bullet` (`" + bullet + "`) and `bulletOther` (`" + bulletOther + "`) to be different"
      );
    }
    return bulletOther;
  }
  function checkBulletOrdered(state) {
    const marker = state.options.bulletOrdered || ".";
    if (marker !== "." && marker !== ")") {
      throw new Error(
        "Cannot serialize items with `" + marker + "` for `options.bulletOrdered`, expected `.` or `)`"
      );
    }
    return marker;
  }
  function checkRule(state) {
    const marker = state.options.rule || "*";
    if (marker !== "*" && marker !== "-" && marker !== "_") {
      throw new Error(
        "Cannot serialize rules with `" + marker + "` for `options.rule`, expected `*`, `-`, or `_`"
      );
    }
    return marker;
  }
  function list(node2, parent, state, info) {
    const exit2 = state.enter("list");
    const bulletCurrent = state.bulletCurrent;
    let bullet = node2.ordered ? checkBulletOrdered(state) : checkBullet(state);
    const bulletOther = node2.ordered ? bullet === "." ? ")" : "." : checkBulletOther(state);
    let useDifferentMarker = parent && state.bulletLastUsed ? bullet === state.bulletLastUsed : false;
    if (!node2.ordered) {
      const firstListItem = node2.children ? node2.children[0] : void 0;
      if (
        // Bullet could be used as a thematic break marker:
        (bullet === "*" || bullet === "-") && // Empty first list item:
        firstListItem && (!firstListItem.children || !firstListItem.children[0]) && // Directly in two other list items:
        state.stack[state.stack.length - 1] === "list" && state.stack[state.stack.length - 2] === "listItem" && state.stack[state.stack.length - 3] === "list" && state.stack[state.stack.length - 4] === "listItem" && // That are each the first child.
        state.indexStack[state.indexStack.length - 1] === 0 && state.indexStack[state.indexStack.length - 2] === 0 && state.indexStack[state.indexStack.length - 3] === 0
      ) {
        useDifferentMarker = true;
      }
      if (checkRule(state) === bullet && firstListItem) {
        let index2 = -1;
        while (++index2 < node2.children.length) {
          const item = node2.children[index2];
          if (item && item.type === "listItem" && item.children && item.children[0] && item.children[0].type === "thematicBreak") {
            useDifferentMarker = true;
            break;
          }
        }
      }
    }
    if (useDifferentMarker) {
      bullet = bulletOther;
    }
    state.bulletCurrent = bullet;
    const value = state.containerFlow(node2, info);
    state.bulletLastUsed = bullet;
    state.bulletCurrent = bulletCurrent;
    exit2();
    return value;
  }
  function checkListItemIndent(state) {
    const style = state.options.listItemIndent || "one";
    if (style !== "tab" && style !== "one" && style !== "mixed") {
      throw new Error(
        "Cannot serialize items with `" + style + "` for `options.listItemIndent`, expected `tab`, `one`, or `mixed`"
      );
    }
    return style;
  }
  function listItem(node2, parent, state, info) {
    const listItemIndent = checkListItemIndent(state);
    let bullet = state.bulletCurrent || checkBullet(state);
    if (parent && parent.type === "list" && parent.ordered) {
      bullet = (typeof parent.start === "number" && parent.start > -1 ? parent.start : 1) + (state.options.incrementListMarker === false ? 0 : parent.children.indexOf(node2)) + bullet;
    }
    let size = bullet.length + 1;
    if (listItemIndent === "tab" || listItemIndent === "mixed" && (parent && parent.type === "list" && parent.spread || node2.spread)) {
      size = Math.ceil(size / 4) * 4;
    }
    const tracker = state.createTracker(info);
    tracker.move(bullet + " ".repeat(size - bullet.length));
    tracker.shift(size);
    const exit2 = state.enter("listItem");
    const value = state.indentLines(
      state.containerFlow(node2, tracker.current()),
      map2
    );
    exit2();
    return value;
    function map2(line, index2, blank) {
      if (index2) {
        return (blank ? "" : " ".repeat(size)) + line;
      }
      return (blank ? bullet : bullet + " ".repeat(size - bullet.length)) + line;
    }
  }
  function paragraph(node2, _, state, info) {
    const exit2 = state.enter("paragraph");
    const subexit = state.enter("phrasing");
    const value = state.containerPhrasing(node2, info);
    subexit();
    exit2();
    return value;
  }
  const phrasing = (
    /** @type {(node?: unknown) => node is Exclude<PhrasingContent, Html>} */
    convert([
      "break",
      "delete",
      "emphasis",
      // To do: next major: removed since footnotes were added to GFM.
      "footnote",
      "footnoteReference",
      "image",
      "imageReference",
      "inlineCode",
      // Enabled by `mdast-util-math`:
      "inlineMath",
      "link",
      "linkReference",
      // Enabled by `mdast-util-mdx`:
      "mdxJsxTextElement",
      // Enabled by `mdast-util-mdx`:
      "mdxTextExpression",
      "strong",
      "text",
      // Enabled by `mdast-util-directive`:
      "textDirective"
    ])
  );
  function root(node2, _, state, info) {
    const hasPhrasing = node2.children.some(function(d) {
      return phrasing(d);
    });
    const fn = hasPhrasing ? state.containerPhrasing : state.containerFlow;
    return fn.call(state, node2, info);
  }
  function checkStrong(state) {
    const marker = state.options.strong || "*";
    if (marker !== "*" && marker !== "_") {
      throw new Error(
        "Cannot serialize strong with `" + marker + "` for `options.strong`, expected `*`, or `_`"
      );
    }
    return marker;
  }
  strong.peek = strongPeek;
  function strong(node2, _, state, info) {
    const marker = checkStrong(state);
    const exit2 = state.enter("strong");
    const tracker = state.createTracker(info);
    let value = tracker.move(marker + marker);
    value += tracker.move(
      state.containerPhrasing(node2, {
        before: value,
        after: marker,
        ...tracker.current()
      })
    );
    value += tracker.move(marker + marker);
    exit2();
    return value;
  }
  function strongPeek(_, _1, state) {
    return state.options.strong || "*";
  }
  function text$1(node2, _, state, info) {
    return state.safe(node2.value, info);
  }
  function checkRuleRepetition(state) {
    const repetition = state.options.ruleRepetition || 3;
    if (repetition < 3) {
      throw new Error(
        "Cannot serialize rules with repetition `" + repetition + "` for `options.ruleRepetition`, expected `3` or more"
      );
    }
    return repetition;
  }
  function thematicBreak(_, _1, state) {
    const value = (checkRule(state) + (state.options.ruleSpaces ? " " : "")).repeat(checkRuleRepetition(state));
    return state.options.ruleSpaces ? value.slice(0, -1) : value;
  }
  const handle = {
    blockquote,
    break: hardBreak,
    code: code$1,
    definition,
    emphasis,
    hardBreak,
    heading,
    html,
    image,
    imageReference,
    inlineCode,
    link,
    linkReference,
    list,
    listItem,
    paragraph,
    root,
    strong,
    text: text$1,
    thematicBreak
  };
  function gfmTableFromMarkdown() {
    return {
      enter: {
        table: enterTable,
        tableData: enterCell,
        tableHeader: enterCell,
        tableRow: enterRow
      },
      exit: {
        codeText: exitCodeText,
        table: exitTable,
        tableData: exit,
        tableHeader: exit,
        tableRow: exit
      }
    };
  }
  function enterTable(token) {
    const align = token._align;
    this.enter(
      {
        type: "table",
        align: align.map(function(d) {
          return d === "none" ? null : d;
        }),
        children: []
      },
      token
    );
    this.data.inTable = true;
  }
  function exitTable(token) {
    this.exit(token);
    this.data.inTable = void 0;
  }
  function enterRow(token) {
    this.enter({ type: "tableRow", children: [] }, token);
  }
  function exit(token) {
    this.exit(token);
  }
  function enterCell(token) {
    this.enter({ type: "tableCell", children: [] }, token);
  }
  function exitCodeText(token) {
    let value = this.resume();
    if (this.data.inTable) {
      value = value.replace(/\\([\\|])/g, replace);
    }
    const node2 = this.stack[this.stack.length - 1];
    ok$1(node2.type === "inlineCode");
    node2.value = value;
    this.exit(token);
  }
  function replace($0, $1) {
    return $1 === "|" ? $1 : $0;
  }
  function gfmTableToMarkdown(options) {
    const settings = options || {};
    const padding = settings.tableCellPadding;
    const alignDelimiters = settings.tablePipeAlign;
    const stringLength = settings.stringLength;
    const around = padding ? " " : "|";
    return {
      unsafe: [
        { character: "\r", inConstruct: "tableCell" },
        { character: "\n", inConstruct: "tableCell" },
        // A pipe, when followed by a tab or space (padding), or a dash or colon
        // (unpadded delimiter row), could result in a table.
        { atBreak: true, character: "|", after: "[	 :-]" },
        // A pipe in a cell must be encoded.
        { character: "|", inConstruct: "tableCell" },
        // A colon must be followed by a dash, in which case it could start a
        // delimiter row.
        { atBreak: true, character: ":", after: "-" },
        // A delimiter row can also start with a dash, when followed by more
        // dashes, a colon, or a pipe.
        // This is a stricter version than the built in check for lists, thematic
        // breaks, and setex heading underlines though:
        // <https://github.com/syntax-tree/mdast-util-to-markdown/blob/51a2038/lib/unsafe.js#L57>
        { atBreak: true, character: "-", after: "[:|-]" }
      ],
      handlers: {
        inlineCode: inlineCodeWithTable,
        table: handleTable,
        tableCell: handleTableCell,
        tableRow: handleTableRow
      }
    };
    function handleTable(node2, _, state, info) {
      return serializeData(handleTableAsData(node2, state, info), node2.align);
    }
    function handleTableRow(node2, _, state, info) {
      const row = handleTableRowAsData(node2, state, info);
      const value = serializeData([row]);
      return value.slice(0, value.indexOf("\n"));
    }
    function handleTableCell(node2, _, state, info) {
      const exit2 = state.enter("tableCell");
      const subexit = state.enter("phrasing");
      const value = state.containerPhrasing(node2, {
        ...info,
        before: around,
        after: around
      });
      subexit();
      exit2();
      return value;
    }
    function serializeData(matrix, align) {
      return markdownTable(matrix, {
        align,
        // @ts-expect-error: `markdown-table` types should support `null`.
        alignDelimiters,
        // @ts-expect-error: `markdown-table` types should support `null`.
        padding,
        // @ts-expect-error: `markdown-table` types should support `null`.
        stringLength
      });
    }
    function handleTableAsData(node2, state, info) {
      const children = node2.children;
      let index2 = -1;
      const result = [];
      const subexit = state.enter("table");
      while (++index2 < children.length) {
        result[index2] = handleTableRowAsData(children[index2], state, info);
      }
      subexit();
      return result;
    }
    function handleTableRowAsData(node2, state, info) {
      const children = node2.children;
      let index2 = -1;
      const result = [];
      const subexit = state.enter("tableRow");
      while (++index2 < children.length) {
        result[index2] = handleTableCell(children[index2], node2, state, info);
      }
      subexit();
      return result;
    }
    function inlineCodeWithTable(node2, parent, state) {
      let value = handle.inlineCode(node2, parent, state);
      if (state.stack.includes("tableCell")) {
        value = value.replace(/\|/g, "\\$&");
      }
      return value;
    }
  }
  function gfmTaskListItemFromMarkdown() {
    return {
      exit: {
        taskListCheckValueChecked: exitCheck,
        taskListCheckValueUnchecked: exitCheck,
        paragraph: exitParagraphWithTaskListItem
      }
    };
  }
  function gfmTaskListItemToMarkdown() {
    return {
      unsafe: [{ atBreak: true, character: "-", after: "[:|-]" }],
      handlers: { listItem: listItemWithTaskListItem }
    };
  }
  function exitCheck(token) {
    const node2 = this.stack[this.stack.length - 2];
    ok$1(node2.type === "listItem");
    node2.checked = token.type === "taskListCheckValueChecked";
  }
  function exitParagraphWithTaskListItem(token) {
    const parent = this.stack[this.stack.length - 2];
    if (parent && parent.type === "listItem" && typeof parent.checked === "boolean") {
      const node2 = this.stack[this.stack.length - 1];
      ok$1(node2.type === "paragraph");
      const head = node2.children[0];
      if (head && head.type === "text") {
        const siblings = parent.children;
        let index2 = -1;
        let firstParaghraph;
        while (++index2 < siblings.length) {
          const sibling = siblings[index2];
          if (sibling.type === "paragraph") {
            firstParaghraph = sibling;
            break;
          }
        }
        if (firstParaghraph === node2) {
          head.value = head.value.slice(1);
          if (head.value.length === 0) {
            node2.children.shift();
          } else if (node2.position && head.position && typeof head.position.start.offset === "number") {
            head.position.start.column++;
            head.position.start.offset++;
            node2.position.start = Object.assign({}, head.position.start);
          }
        }
      }
    }
    this.exit(token);
  }
  function listItemWithTaskListItem(node2, parent, state, info) {
    const head = node2.children[0];
    const checkable = typeof node2.checked === "boolean" && head && head.type === "paragraph";
    const checkbox = "[" + (node2.checked ? "x" : " ") + "] ";
    const tracker = state.createTracker(info);
    if (checkable) {
      tracker.move(checkbox);
    }
    let value = handle.listItem(node2, parent, state, {
      ...info,
      ...tracker.current()
    });
    if (checkable) {
      value = value.replace(/^(?:[*+-]|\d+\.)([\r\n]| {1,3})/, check);
    }
    return value;
    function check($0) {
      return $0 + checkbox;
    }
  }
  function gfmFromMarkdown() {
    return [
      gfmAutolinkLiteralFromMarkdown(),
      gfmFootnoteFromMarkdown(),
      gfmStrikethroughFromMarkdown(),
      gfmTableFromMarkdown(),
      gfmTaskListItemFromMarkdown()
    ];
  }
  function gfmToMarkdown(options) {
    return {
      extensions: [
        gfmAutolinkLiteralToMarkdown(),
        gfmFootnoteToMarkdown(options),
        gfmStrikethroughToMarkdown(),
        gfmTableToMarkdown(options),
        gfmTaskListItemToMarkdown()
      ]
    };
  }
  const wwwPrefix = {
    tokenize: tokenizeWwwPrefix,
    partial: true
  };
  const domain = {
    tokenize: tokenizeDomain,
    partial: true
  };
  const path = {
    tokenize: tokenizePath,
    partial: true
  };
  const trail = {
    tokenize: tokenizeTrail,
    partial: true
  };
  const emailDomainDotTrail = {
    tokenize: tokenizeEmailDomainDotTrail,
    partial: true
  };
  const wwwAutolink = {
    name: "wwwAutolink",
    tokenize: tokenizeWwwAutolink,
    previous: previousWww
  };
  const protocolAutolink = {
    name: "protocolAutolink",
    tokenize: tokenizeProtocolAutolink,
    previous: previousProtocol
  };
  const emailAutolink = {
    name: "emailAutolink",
    tokenize: tokenizeEmailAutolink,
    previous: previousEmail
  };
  const text = {};
  function gfmAutolinkLiteral() {
    return {
      text
    };
  }
  let code = 48;
  while (code < 123) {
    text[code] = emailAutolink;
    code++;
    if (code === 58) code = 65;
    else if (code === 91) code = 97;
  }
  text[43] = emailAutolink;
  text[45] = emailAutolink;
  text[46] = emailAutolink;
  text[95] = emailAutolink;
  text[72] = [emailAutolink, protocolAutolink];
  text[104] = [emailAutolink, protocolAutolink];
  text[87] = [emailAutolink, wwwAutolink];
  text[119] = [emailAutolink, wwwAutolink];
  function tokenizeEmailAutolink(effects, ok2, nok) {
    const self2 = this;
    let dot;
    let data;
    return start;
    function start(code2) {
      if (!gfmAtext(code2) || !previousEmail.call(self2, self2.previous) || previousUnbalanced(self2.events)) {
        return nok(code2);
      }
      effects.enter("literalAutolink");
      effects.enter("literalAutolinkEmail");
      return atext(code2);
    }
    function atext(code2) {
      if (gfmAtext(code2)) {
        effects.consume(code2);
        return atext;
      }
      if (code2 === 64) {
        effects.consume(code2);
        return emailDomain;
      }
      return nok(code2);
    }
    function emailDomain(code2) {
      if (code2 === 46) {
        return effects.check(emailDomainDotTrail, emailDomainAfter, emailDomainDot)(code2);
      }
      if (code2 === 45 || code2 === 95 || asciiAlphanumeric(code2)) {
        data = true;
        effects.consume(code2);
        return emailDomain;
      }
      return emailDomainAfter(code2);
    }
    function emailDomainDot(code2) {
      effects.consume(code2);
      dot = true;
      return emailDomain;
    }
    function emailDomainAfter(code2) {
      if (data && dot && asciiAlpha(self2.previous)) {
        effects.exit("literalAutolinkEmail");
        effects.exit("literalAutolink");
        return ok2(code2);
      }
      return nok(code2);
    }
  }
  function tokenizeWwwAutolink(effects, ok2, nok) {
    const self2 = this;
    return wwwStart;
    function wwwStart(code2) {
      if (code2 !== 87 && code2 !== 119 || !previousWww.call(self2, self2.previous) || previousUnbalanced(self2.events)) {
        return nok(code2);
      }
      effects.enter("literalAutolink");
      effects.enter("literalAutolinkWww");
      return effects.check(wwwPrefix, effects.attempt(domain, effects.attempt(path, wwwAfter), nok), nok)(code2);
    }
    function wwwAfter(code2) {
      effects.exit("literalAutolinkWww");
      effects.exit("literalAutolink");
      return ok2(code2);
    }
  }
  function tokenizeProtocolAutolink(effects, ok2, nok) {
    const self2 = this;
    let buffer = "";
    let seen = false;
    return protocolStart;
    function protocolStart(code2) {
      if ((code2 === 72 || code2 === 104) && previousProtocol.call(self2, self2.previous) && !previousUnbalanced(self2.events)) {
        effects.enter("literalAutolink");
        effects.enter("literalAutolinkHttp");
        buffer += String.fromCodePoint(code2);
        effects.consume(code2);
        return protocolPrefixInside;
      }
      return nok(code2);
    }
    function protocolPrefixInside(code2) {
      if (asciiAlpha(code2) && buffer.length < 5) {
        buffer += String.fromCodePoint(code2);
        effects.consume(code2);
        return protocolPrefixInside;
      }
      if (code2 === 58) {
        const protocol = buffer.toLowerCase();
        if (protocol === "http" || protocol === "https") {
          effects.consume(code2);
          return protocolSlashesInside;
        }
      }
      return nok(code2);
    }
    function protocolSlashesInside(code2) {
      if (code2 === 47) {
        effects.consume(code2);
        if (seen) {
          return afterProtocol;
        }
        seen = true;
        return protocolSlashesInside;
      }
      return nok(code2);
    }
    function afterProtocol(code2) {
      return code2 === null || asciiControl(code2) || markdownLineEndingOrSpace(code2) || unicodeWhitespace(code2) || unicodePunctuation(code2) ? nok(code2) : effects.attempt(domain, effects.attempt(path, protocolAfter), nok)(code2);
    }
    function protocolAfter(code2) {
      effects.exit("literalAutolinkHttp");
      effects.exit("literalAutolink");
      return ok2(code2);
    }
  }
  function tokenizeWwwPrefix(effects, ok2, nok) {
    let size = 0;
    return wwwPrefixInside;
    function wwwPrefixInside(code2) {
      if ((code2 === 87 || code2 === 119) && size < 3) {
        size++;
        effects.consume(code2);
        return wwwPrefixInside;
      }
      if (code2 === 46 && size === 3) {
        effects.consume(code2);
        return wwwPrefixAfter;
      }
      return nok(code2);
    }
    function wwwPrefixAfter(code2) {
      return code2 === null ? nok(code2) : ok2(code2);
    }
  }
  function tokenizeDomain(effects, ok2, nok) {
    let underscoreInLastSegment;
    let underscoreInLastLastSegment;
    let seen;
    return domainInside;
    function domainInside(code2) {
      if (code2 === 46 || code2 === 95) {
        return effects.check(trail, domainAfter, domainAtPunctuation)(code2);
      }
      if (code2 === null || markdownLineEndingOrSpace(code2) || unicodeWhitespace(code2) || code2 !== 45 && unicodePunctuation(code2)) {
        return domainAfter(code2);
      }
      seen = true;
      effects.consume(code2);
      return domainInside;
    }
    function domainAtPunctuation(code2) {
      if (code2 === 95) {
        underscoreInLastSegment = true;
      } else {
        underscoreInLastLastSegment = underscoreInLastSegment;
        underscoreInLastSegment = void 0;
      }
      effects.consume(code2);
      return domainInside;
    }
    function domainAfter(code2) {
      if (underscoreInLastLastSegment || underscoreInLastSegment || !seen) {
        return nok(code2);
      }
      return ok2(code2);
    }
  }
  function tokenizePath(effects, ok2) {
    let sizeOpen = 0;
    let sizeClose = 0;
    return pathInside;
    function pathInside(code2) {
      if (code2 === 40) {
        sizeOpen++;
        effects.consume(code2);
        return pathInside;
      }
      if (code2 === 41 && sizeClose < sizeOpen) {
        return pathAtPunctuation(code2);
      }
      if (code2 === 33 || code2 === 34 || code2 === 38 || code2 === 39 || code2 === 41 || code2 === 42 || code2 === 44 || code2 === 46 || code2 === 58 || code2 === 59 || code2 === 60 || code2 === 63 || code2 === 93 || code2 === 95 || code2 === 126) {
        return effects.check(trail, ok2, pathAtPunctuation)(code2);
      }
      if (code2 === null || markdownLineEndingOrSpace(code2) || unicodeWhitespace(code2)) {
        return ok2(code2);
      }
      effects.consume(code2);
      return pathInside;
    }
    function pathAtPunctuation(code2) {
      if (code2 === 41) {
        sizeClose++;
      }
      effects.consume(code2);
      return pathInside;
    }
  }
  function tokenizeTrail(effects, ok2, nok) {
    return trail2;
    function trail2(code2) {
      if (code2 === 33 || code2 === 34 || code2 === 39 || code2 === 41 || code2 === 42 || code2 === 44 || code2 === 46 || code2 === 58 || code2 === 59 || code2 === 63 || code2 === 95 || code2 === 126) {
        effects.consume(code2);
        return trail2;
      }
      if (code2 === 38) {
        effects.consume(code2);
        return trailCharacterReferenceStart;
      }
      if (code2 === 93) {
        effects.consume(code2);
        return trailBracketAfter;
      }
      if (
        // `<` is an end.
        code2 === 60 || // So is whitespace.
        code2 === null || markdownLineEndingOrSpace(code2) || unicodeWhitespace(code2)
      ) {
        return ok2(code2);
      }
      return nok(code2);
    }
    function trailBracketAfter(code2) {
      if (code2 === null || code2 === 40 || code2 === 91 || markdownLineEndingOrSpace(code2) || unicodeWhitespace(code2)) {
        return ok2(code2);
      }
      return trail2(code2);
    }
    function trailCharacterReferenceStart(code2) {
      return asciiAlpha(code2) ? trailCharacterReferenceInside(code2) : nok(code2);
    }
    function trailCharacterReferenceInside(code2) {
      if (code2 === 59) {
        effects.consume(code2);
        return trail2;
      }
      if (asciiAlpha(code2)) {
        effects.consume(code2);
        return trailCharacterReferenceInside;
      }
      return nok(code2);
    }
  }
  function tokenizeEmailDomainDotTrail(effects, ok2, nok) {
    return start;
    function start(code2) {
      effects.consume(code2);
      return after;
    }
    function after(code2) {
      return asciiAlphanumeric(code2) ? nok(code2) : ok2(code2);
    }
  }
  function previousWww(code2) {
    return code2 === null || code2 === 40 || code2 === 42 || code2 === 95 || code2 === 91 || code2 === 93 || code2 === 126 || markdownLineEndingOrSpace(code2);
  }
  function previousProtocol(code2) {
    return !asciiAlpha(code2);
  }
  function previousEmail(code2) {
    return !(code2 === 47 || gfmAtext(code2));
  }
  function gfmAtext(code2) {
    return code2 === 43 || code2 === 45 || code2 === 46 || code2 === 95 || asciiAlphanumeric(code2);
  }
  function previousUnbalanced(events) {
    let index2 = events.length;
    let result = false;
    while (index2--) {
      const token = events[index2][1];
      if ((token.type === "labelLink" || token.type === "labelImage") && !token._balanced) {
        result = true;
        break;
      }
      if (token._gfmAutolinkLiteralWalkedInto) {
        result = false;
        break;
      }
    }
    if (events.length > 0 && !result) {
      events[events.length - 1][1]._gfmAutolinkLiteralWalkedInto = true;
    }
    return result;
  }
  const indent = {
    tokenize: tokenizeIndent,
    partial: true
  };
  function gfmFootnote() {
    return {
      document: {
        [91]: {
          name: "gfmFootnoteDefinition",
          tokenize: tokenizeDefinitionStart,
          continuation: {
            tokenize: tokenizeDefinitionContinuation
          },
          exit: gfmFootnoteDefinitionEnd
        }
      },
      text: {
        [91]: {
          name: "gfmFootnoteCall",
          tokenize: tokenizeGfmFootnoteCall
        },
        [93]: {
          name: "gfmPotentialFootnoteCall",
          add: "after",
          tokenize: tokenizePotentialGfmFootnoteCall,
          resolveTo: resolveToPotentialGfmFootnoteCall
        }
      }
    };
  }
  function tokenizePotentialGfmFootnoteCall(effects, ok2, nok) {
    const self2 = this;
    let index2 = self2.events.length;
    const defined = self2.parser.gfmFootnotes || (self2.parser.gfmFootnotes = []);
    let labelStart;
    while (index2--) {
      const token = self2.events[index2][1];
      if (token.type === "labelImage") {
        labelStart = token;
        break;
      }
      if (token.type === "gfmFootnoteCall" || token.type === "labelLink" || token.type === "label" || token.type === "image" || token.type === "link") {
        break;
      }
    }
    return start;
    function start(code2) {
      if (!labelStart || !labelStart._balanced) {
        return nok(code2);
      }
      const id = normalizeIdentifier(self2.sliceSerialize({
        start: labelStart.end,
        end: self2.now()
      }));
      if (id.codePointAt(0) !== 94 || !defined.includes(id.slice(1))) {
        return nok(code2);
      }
      effects.enter("gfmFootnoteCallLabelMarker");
      effects.consume(code2);
      effects.exit("gfmFootnoteCallLabelMarker");
      return ok2(code2);
    }
  }
  function resolveToPotentialGfmFootnoteCall(events, context) {
    let index2 = events.length;
    while (index2--) {
      if (events[index2][1].type === "labelImage" && events[index2][0] === "enter") {
        events[index2][1];
        break;
      }
    }
    events[index2 + 1][1].type = "data";
    events[index2 + 3][1].type = "gfmFootnoteCallLabelMarker";
    const call = {
      type: "gfmFootnoteCall",
      start: Object.assign({}, events[index2 + 3][1].start),
      end: Object.assign({}, events[events.length - 1][1].end)
    };
    const marker = {
      type: "gfmFootnoteCallMarker",
      start: Object.assign({}, events[index2 + 3][1].end),
      end: Object.assign({}, events[index2 + 3][1].end)
    };
    marker.end.column++;
    marker.end.offset++;
    marker.end._bufferIndex++;
    const string2 = {
      type: "gfmFootnoteCallString",
      start: Object.assign({}, marker.end),
      end: Object.assign({}, events[events.length - 1][1].start)
    };
    const chunk = {
      type: "chunkString",
      contentType: "string",
      start: Object.assign({}, string2.start),
      end: Object.assign({}, string2.end)
    };
    const replacement = [
      // Take the `labelImageMarker` (now `data`, the `!`)
      events[index2 + 1],
      events[index2 + 2],
      ["enter", call, context],
      // The `[`
      events[index2 + 3],
      events[index2 + 4],
      // The `^`.
      ["enter", marker, context],
      ["exit", marker, context],
      // Everything in between.
      ["enter", string2, context],
      ["enter", chunk, context],
      ["exit", chunk, context],
      ["exit", string2, context],
      // The ending (`]`, properly parsed and labelled).
      events[events.length - 2],
      events[events.length - 1],
      ["exit", call, context]
    ];
    events.splice(index2, events.length - index2 + 1, ...replacement);
    return events;
  }
  function tokenizeGfmFootnoteCall(effects, ok2, nok) {
    const self2 = this;
    const defined = self2.parser.gfmFootnotes || (self2.parser.gfmFootnotes = []);
    let size = 0;
    let data;
    return start;
    function start(code2) {
      effects.enter("gfmFootnoteCall");
      effects.enter("gfmFootnoteCallLabelMarker");
      effects.consume(code2);
      effects.exit("gfmFootnoteCallLabelMarker");
      return callStart;
    }
    function callStart(code2) {
      if (code2 !== 94) return nok(code2);
      effects.enter("gfmFootnoteCallMarker");
      effects.consume(code2);
      effects.exit("gfmFootnoteCallMarker");
      effects.enter("gfmFootnoteCallString");
      effects.enter("chunkString").contentType = "string";
      return callData;
    }
    function callData(code2) {
      if (
        // Too long.
        size > 999 || // Closing brace with nothing.
        code2 === 93 && !data || // Space or tab is not supported by GFM for some reason.
        // `\n` and `[` not being supported makes sense.
        code2 === null || code2 === 91 || markdownLineEndingOrSpace(code2)
      ) {
        return nok(code2);
      }
      if (code2 === 93) {
        effects.exit("chunkString");
        const token = effects.exit("gfmFootnoteCallString");
        if (!defined.includes(normalizeIdentifier(self2.sliceSerialize(token)))) {
          return nok(code2);
        }
        effects.enter("gfmFootnoteCallLabelMarker");
        effects.consume(code2);
        effects.exit("gfmFootnoteCallLabelMarker");
        effects.exit("gfmFootnoteCall");
        return ok2;
      }
      if (!markdownLineEndingOrSpace(code2)) {
        data = true;
      }
      size++;
      effects.consume(code2);
      return code2 === 92 ? callEscape : callData;
    }
    function callEscape(code2) {
      if (code2 === 91 || code2 === 92 || code2 === 93) {
        effects.consume(code2);
        size++;
        return callData;
      }
      return callData(code2);
    }
  }
  function tokenizeDefinitionStart(effects, ok2, nok) {
    const self2 = this;
    const defined = self2.parser.gfmFootnotes || (self2.parser.gfmFootnotes = []);
    let identifier;
    let size = 0;
    let data;
    return start;
    function start(code2) {
      effects.enter("gfmFootnoteDefinition")._container = true;
      effects.enter("gfmFootnoteDefinitionLabel");
      effects.enter("gfmFootnoteDefinitionLabelMarker");
      effects.consume(code2);
      effects.exit("gfmFootnoteDefinitionLabelMarker");
      return labelAtMarker;
    }
    function labelAtMarker(code2) {
      if (code2 === 94) {
        effects.enter("gfmFootnoteDefinitionMarker");
        effects.consume(code2);
        effects.exit("gfmFootnoteDefinitionMarker");
        effects.enter("gfmFootnoteDefinitionLabelString");
        effects.enter("chunkString").contentType = "string";
        return labelInside;
      }
      return nok(code2);
    }
    function labelInside(code2) {
      if (
        // Too long.
        size > 999 || // Closing brace with nothing.
        code2 === 93 && !data || // Space or tab is not supported by GFM for some reason.
        // `\n` and `[` not being supported makes sense.
        code2 === null || code2 === 91 || markdownLineEndingOrSpace(code2)
      ) {
        return nok(code2);
      }
      if (code2 === 93) {
        effects.exit("chunkString");
        const token = effects.exit("gfmFootnoteDefinitionLabelString");
        identifier = normalizeIdentifier(self2.sliceSerialize(token));
        effects.enter("gfmFootnoteDefinitionLabelMarker");
        effects.consume(code2);
        effects.exit("gfmFootnoteDefinitionLabelMarker");
        effects.exit("gfmFootnoteDefinitionLabel");
        return labelAfter;
      }
      if (!markdownLineEndingOrSpace(code2)) {
        data = true;
      }
      size++;
      effects.consume(code2);
      return code2 === 92 ? labelEscape : labelInside;
    }
    function labelEscape(code2) {
      if (code2 === 91 || code2 === 92 || code2 === 93) {
        effects.consume(code2);
        size++;
        return labelInside;
      }
      return labelInside(code2);
    }
    function labelAfter(code2) {
      if (code2 === 58) {
        effects.enter("definitionMarker");
        effects.consume(code2);
        effects.exit("definitionMarker");
        if (!defined.includes(identifier)) {
          defined.push(identifier);
        }
        return factorySpace(effects, whitespaceAfter, "gfmFootnoteDefinitionWhitespace");
      }
      return nok(code2);
    }
    function whitespaceAfter(code2) {
      return ok2(code2);
    }
  }
  function tokenizeDefinitionContinuation(effects, ok2, nok) {
    return effects.check(blankLine, ok2, effects.attempt(indent, ok2, nok));
  }
  function gfmFootnoteDefinitionEnd(effects) {
    effects.exit("gfmFootnoteDefinition");
  }
  function tokenizeIndent(effects, ok2, nok) {
    const self2 = this;
    return factorySpace(effects, afterPrefix, "gfmFootnoteDefinitionIndent", 4 + 1);
    function afterPrefix(code2) {
      const tail = self2.events[self2.events.length - 1];
      return tail && tail[1].type === "gfmFootnoteDefinitionIndent" && tail[2].sliceSerialize(tail[1], true).length === 4 ? ok2(code2) : nok(code2);
    }
  }
  function gfmStrikethrough(options) {
    const options_ = options || {};
    let single = options_.singleTilde;
    const tokenizer = {
      name: "strikethrough",
      tokenize: tokenizeStrikethrough,
      resolveAll: resolveAllStrikethrough
    };
    if (single === null || single === void 0) {
      single = true;
    }
    return {
      text: {
        [126]: tokenizer
      },
      insideSpan: {
        null: [tokenizer]
      },
      attentionMarkers: {
        null: [126]
      }
    };
    function resolveAllStrikethrough(events, context) {
      let index2 = -1;
      while (++index2 < events.length) {
        if (events[index2][0] === "enter" && events[index2][1].type === "strikethroughSequenceTemporary" && events[index2][1]._close) {
          let open = index2;
          while (open--) {
            if (events[open][0] === "exit" && events[open][1].type === "strikethroughSequenceTemporary" && events[open][1]._open && // If the sizes are the same:
            events[index2][1].end.offset - events[index2][1].start.offset === events[open][1].end.offset - events[open][1].start.offset) {
              events[index2][1].type = "strikethroughSequence";
              events[open][1].type = "strikethroughSequence";
              const strikethrough2 = {
                type: "strikethrough",
                start: Object.assign({}, events[open][1].start),
                end: Object.assign({}, events[index2][1].end)
              };
              const text2 = {
                type: "strikethroughText",
                start: Object.assign({}, events[open][1].end),
                end: Object.assign({}, events[index2][1].start)
              };
              const nextEvents = [["enter", strikethrough2, context], ["enter", events[open][1], context], ["exit", events[open][1], context], ["enter", text2, context]];
              const insideSpan2 = context.parser.constructs.insideSpan.null;
              if (insideSpan2) {
                splice(nextEvents, nextEvents.length, 0, resolveAll(insideSpan2, events.slice(open + 1, index2), context));
              }
              splice(nextEvents, nextEvents.length, 0, [["exit", text2, context], ["enter", events[index2][1], context], ["exit", events[index2][1], context], ["exit", strikethrough2, context]]);
              splice(events, open - 1, index2 - open + 3, nextEvents);
              index2 = open + nextEvents.length - 2;
              break;
            }
          }
        }
      }
      index2 = -1;
      while (++index2 < events.length) {
        if (events[index2][1].type === "strikethroughSequenceTemporary") {
          events[index2][1].type = "data";
        }
      }
      return events;
    }
    function tokenizeStrikethrough(effects, ok2, nok) {
      const previous2 = this.previous;
      const events = this.events;
      let size = 0;
      return start;
      function start(code2) {
        if (previous2 === 126 && events[events.length - 1][1].type !== "characterEscape") {
          return nok(code2);
        }
        effects.enter("strikethroughSequenceTemporary");
        return more(code2);
      }
      function more(code2) {
        const before = classifyCharacter(previous2);
        if (code2 === 126) {
          if (size > 1) return nok(code2);
          effects.consume(code2);
          size++;
          return more;
        }
        if (size < 2 && !single) return nok(code2);
        const token = effects.exit("strikethroughSequenceTemporary");
        const after = classifyCharacter(code2);
        token._open = !after || after === 2 && Boolean(before);
        token._close = !before || before === 2 && Boolean(after);
        return ok2(code2);
      }
    }
  }
  class EditMap {
    /**
     * Create a new edit map.
     */
    constructor() {
      this.map = [];
    }
    /**
     * Create an edit: a remove and/or add at a certain place.
     *
     * @param {number} index
     * @param {number} remove
     * @param {Array<Event>} add
     * @returns {undefined}
     */
    add(index2, remove, add) {
      addImplementation(this, index2, remove, add);
    }
    // To do: add this when moving to `micromark`.
    // /**
    //  * Create an edit: but insert `add` before existing additions.
    //  *
    //  * @param {number} index
    //  * @param {number} remove
    //  * @param {Array<Event>} add
    //  * @returns {undefined}
    //  */
    // addBefore(index, remove, add) {
    //   addImplementation(this, index, remove, add, true)
    // }
    /**
     * Done, change the events.
     *
     * @param {Array<Event>} events
     * @returns {undefined}
     */
    consume(events) {
      this.map.sort(function(a, b) {
        return a[0] - b[0];
      });
      if (this.map.length === 0) {
        return;
      }
      let index2 = this.map.length;
      const vecs = [];
      while (index2 > 0) {
        index2 -= 1;
        vecs.push(events.slice(this.map[index2][0] + this.map[index2][1]), this.map[index2][2]);
        events.length = this.map[index2][0];
      }
      vecs.push(events.slice());
      events.length = 0;
      let slice = vecs.pop();
      while (slice) {
        for (const element2 of slice) {
          events.push(element2);
        }
        slice = vecs.pop();
      }
      this.map.length = 0;
    }
  }
  function addImplementation(editMap, at, remove, add) {
    let index2 = 0;
    if (remove === 0 && add.length === 0) {
      return;
    }
    while (index2 < editMap.map.length) {
      if (editMap.map[index2][0] === at) {
        editMap.map[index2][1] += remove;
        editMap.map[index2][2].push(...add);
        return;
      }
      index2 += 1;
    }
    editMap.map.push([at, remove, add]);
  }
  function gfmTableAlign(events, index2) {
    let inDelimiterRow = false;
    const align = [];
    while (index2 < events.length) {
      const event = events[index2];
      if (inDelimiterRow) {
        if (event[0] === "enter") {
          if (event[1].type === "tableContent") {
            align.push(events[index2 + 1][1].type === "tableDelimiterMarker" ? "left" : "none");
          }
        } else if (event[1].type === "tableContent") {
          if (events[index2 - 1][1].type === "tableDelimiterMarker") {
            const alignIndex = align.length - 1;
            align[alignIndex] = align[alignIndex] === "left" ? "center" : "right";
          }
        } else if (event[1].type === "tableDelimiterRow") {
          break;
        }
      } else if (event[0] === "enter" && event[1].type === "tableDelimiterRow") {
        inDelimiterRow = true;
      }
      index2 += 1;
    }
    return align;
  }
  function gfmTable() {
    return {
      flow: {
        null: {
          name: "table",
          tokenize: tokenizeTable,
          resolveAll: resolveTable
        }
      }
    };
  }
  function tokenizeTable(effects, ok2, nok) {
    const self2 = this;
    let size = 0;
    let sizeB = 0;
    let seen;
    return start;
    function start(code2) {
      let index2 = self2.events.length - 1;
      while (index2 > -1) {
        const type = self2.events[index2][1].type;
        if (type === "lineEnding" || // Note: markdown-rs uses `whitespace` instead of `linePrefix`
        type === "linePrefix") index2--;
        else break;
      }
      const tail = index2 > -1 ? self2.events[index2][1].type : null;
      const next = tail === "tableHead" || tail === "tableRow" ? bodyRowStart : headRowBefore;
      if (next === bodyRowStart && self2.parser.lazy[self2.now().line]) {
        return nok(code2);
      }
      return next(code2);
    }
    function headRowBefore(code2) {
      effects.enter("tableHead");
      effects.enter("tableRow");
      return headRowStart(code2);
    }
    function headRowStart(code2) {
      if (code2 === 124) {
        return headRowBreak(code2);
      }
      seen = true;
      sizeB += 1;
      return headRowBreak(code2);
    }
    function headRowBreak(code2) {
      if (code2 === null) {
        return nok(code2);
      }
      if (markdownLineEnding(code2)) {
        if (sizeB > 1) {
          sizeB = 0;
          self2.interrupt = true;
          effects.exit("tableRow");
          effects.enter("lineEnding");
          effects.consume(code2);
          effects.exit("lineEnding");
          return headDelimiterStart;
        }
        return nok(code2);
      }
      if (markdownSpace(code2)) {
        return factorySpace(effects, headRowBreak, "whitespace")(code2);
      }
      sizeB += 1;
      if (seen) {
        seen = false;
        size += 1;
      }
      if (code2 === 124) {
        effects.enter("tableCellDivider");
        effects.consume(code2);
        effects.exit("tableCellDivider");
        seen = true;
        return headRowBreak;
      }
      effects.enter("data");
      return headRowData(code2);
    }
    function headRowData(code2) {
      if (code2 === null || code2 === 124 || markdownLineEndingOrSpace(code2)) {
        effects.exit("data");
        return headRowBreak(code2);
      }
      effects.consume(code2);
      return code2 === 92 ? headRowEscape : headRowData;
    }
    function headRowEscape(code2) {
      if (code2 === 92 || code2 === 124) {
        effects.consume(code2);
        return headRowData;
      }
      return headRowData(code2);
    }
    function headDelimiterStart(code2) {
      self2.interrupt = false;
      if (self2.parser.lazy[self2.now().line]) {
        return nok(code2);
      }
      effects.enter("tableDelimiterRow");
      seen = false;
      if (markdownSpace(code2)) {
        return factorySpace(effects, headDelimiterBefore, "linePrefix", self2.parser.constructs.disable.null.includes("codeIndented") ? void 0 : 4)(code2);
      }
      return headDelimiterBefore(code2);
    }
    function headDelimiterBefore(code2) {
      if (code2 === 45 || code2 === 58) {
        return headDelimiterValueBefore(code2);
      }
      if (code2 === 124) {
        seen = true;
        effects.enter("tableCellDivider");
        effects.consume(code2);
        effects.exit("tableCellDivider");
        return headDelimiterCellBefore;
      }
      return headDelimiterNok(code2);
    }
    function headDelimiterCellBefore(code2) {
      if (markdownSpace(code2)) {
        return factorySpace(effects, headDelimiterValueBefore, "whitespace")(code2);
      }
      return headDelimiterValueBefore(code2);
    }
    function headDelimiterValueBefore(code2) {
      if (code2 === 58) {
        sizeB += 1;
        seen = true;
        effects.enter("tableDelimiterMarker");
        effects.consume(code2);
        effects.exit("tableDelimiterMarker");
        return headDelimiterLeftAlignmentAfter;
      }
      if (code2 === 45) {
        sizeB += 1;
        return headDelimiterLeftAlignmentAfter(code2);
      }
      if (code2 === null || markdownLineEnding(code2)) {
        return headDelimiterCellAfter(code2);
      }
      return headDelimiterNok(code2);
    }
    function headDelimiterLeftAlignmentAfter(code2) {
      if (code2 === 45) {
        effects.enter("tableDelimiterFiller");
        return headDelimiterFiller(code2);
      }
      return headDelimiterNok(code2);
    }
    function headDelimiterFiller(code2) {
      if (code2 === 45) {
        effects.consume(code2);
        return headDelimiterFiller;
      }
      if (code2 === 58) {
        seen = true;
        effects.exit("tableDelimiterFiller");
        effects.enter("tableDelimiterMarker");
        effects.consume(code2);
        effects.exit("tableDelimiterMarker");
        return headDelimiterRightAlignmentAfter;
      }
      effects.exit("tableDelimiterFiller");
      return headDelimiterRightAlignmentAfter(code2);
    }
    function headDelimiterRightAlignmentAfter(code2) {
      if (markdownSpace(code2)) {
        return factorySpace(effects, headDelimiterCellAfter, "whitespace")(code2);
      }
      return headDelimiterCellAfter(code2);
    }
    function headDelimiterCellAfter(code2) {
      if (code2 === 124) {
        return headDelimiterBefore(code2);
      }
      if (code2 === null || markdownLineEnding(code2)) {
        if (!seen || size !== sizeB) {
          return headDelimiterNok(code2);
        }
        effects.exit("tableDelimiterRow");
        effects.exit("tableHead");
        return ok2(code2);
      }
      return headDelimiterNok(code2);
    }
    function headDelimiterNok(code2) {
      return nok(code2);
    }
    function bodyRowStart(code2) {
      effects.enter("tableRow");
      return bodyRowBreak(code2);
    }
    function bodyRowBreak(code2) {
      if (code2 === 124) {
        effects.enter("tableCellDivider");
        effects.consume(code2);
        effects.exit("tableCellDivider");
        return bodyRowBreak;
      }
      if (code2 === null || markdownLineEnding(code2)) {
        effects.exit("tableRow");
        return ok2(code2);
      }
      if (markdownSpace(code2)) {
        return factorySpace(effects, bodyRowBreak, "whitespace")(code2);
      }
      effects.enter("data");
      return bodyRowData(code2);
    }
    function bodyRowData(code2) {
      if (code2 === null || code2 === 124 || markdownLineEndingOrSpace(code2)) {
        effects.exit("data");
        return bodyRowBreak(code2);
      }
      effects.consume(code2);
      return code2 === 92 ? bodyRowEscape : bodyRowData;
    }
    function bodyRowEscape(code2) {
      if (code2 === 92 || code2 === 124) {
        effects.consume(code2);
        return bodyRowData;
      }
      return bodyRowData(code2);
    }
  }
  function resolveTable(events, context) {
    let index2 = -1;
    let inFirstCellAwaitingPipe = true;
    let rowKind = 0;
    let lastCell = [0, 0, 0, 0];
    let cell = [0, 0, 0, 0];
    let afterHeadAwaitingFirstBodyRow = false;
    let lastTableEnd = 0;
    let currentTable;
    let currentBody;
    let currentCell;
    const map2 = new EditMap();
    while (++index2 < events.length) {
      const event = events[index2];
      const token = event[1];
      if (event[0] === "enter") {
        if (token.type === "tableHead") {
          afterHeadAwaitingFirstBodyRow = false;
          if (lastTableEnd !== 0) {
            flushTableEnd(map2, context, lastTableEnd, currentTable, currentBody);
            currentBody = void 0;
            lastTableEnd = 0;
          }
          currentTable = {
            type: "table",
            start: Object.assign({}, token.start),
            // Note: correct end is set later.
            end: Object.assign({}, token.end)
          };
          map2.add(index2, 0, [["enter", currentTable, context]]);
        } else if (token.type === "tableRow" || token.type === "tableDelimiterRow") {
          inFirstCellAwaitingPipe = true;
          currentCell = void 0;
          lastCell = [0, 0, 0, 0];
          cell = [0, index2 + 1, 0, 0];
          if (afterHeadAwaitingFirstBodyRow) {
            afterHeadAwaitingFirstBodyRow = false;
            currentBody = {
              type: "tableBody",
              start: Object.assign({}, token.start),
              // Note: correct end is set later.
              end: Object.assign({}, token.end)
            };
            map2.add(index2, 0, [["enter", currentBody, context]]);
          }
          rowKind = token.type === "tableDelimiterRow" ? 2 : currentBody ? 3 : 1;
        } else if (rowKind && (token.type === "data" || token.type === "tableDelimiterMarker" || token.type === "tableDelimiterFiller")) {
          inFirstCellAwaitingPipe = false;
          if (cell[2] === 0) {
            if (lastCell[1] !== 0) {
              cell[0] = cell[1];
              currentCell = flushCell(map2, context, lastCell, rowKind, void 0, currentCell);
              lastCell = [0, 0, 0, 0];
            }
            cell[2] = index2;
          }
        } else if (token.type === "tableCellDivider") {
          if (inFirstCellAwaitingPipe) {
            inFirstCellAwaitingPipe = false;
          } else {
            if (lastCell[1] !== 0) {
              cell[0] = cell[1];
              currentCell = flushCell(map2, context, lastCell, rowKind, void 0, currentCell);
            }
            lastCell = cell;
            cell = [lastCell[1], index2, 0, 0];
          }
        }
      } else if (token.type === "tableHead") {
        afterHeadAwaitingFirstBodyRow = true;
        lastTableEnd = index2;
      } else if (token.type === "tableRow" || token.type === "tableDelimiterRow") {
        lastTableEnd = index2;
        if (lastCell[1] !== 0) {
          cell[0] = cell[1];
          currentCell = flushCell(map2, context, lastCell, rowKind, index2, currentCell);
        } else if (cell[1] !== 0) {
          currentCell = flushCell(map2, context, cell, rowKind, index2, currentCell);
        }
        rowKind = 0;
      } else if (rowKind && (token.type === "data" || token.type === "tableDelimiterMarker" || token.type === "tableDelimiterFiller")) {
        cell[3] = index2;
      }
    }
    if (lastTableEnd !== 0) {
      flushTableEnd(map2, context, lastTableEnd, currentTable, currentBody);
    }
    map2.consume(context.events);
    index2 = -1;
    while (++index2 < context.events.length) {
      const event = context.events[index2];
      if (event[0] === "enter" && event[1].type === "table") {
        event[1]._align = gfmTableAlign(context.events, index2);
      }
    }
    return events;
  }
  function flushCell(map2, context, range, rowKind, rowEnd, previousCell) {
    const groupName = rowKind === 1 ? "tableHeader" : rowKind === 2 ? "tableDelimiter" : "tableData";
    const valueName = "tableContent";
    if (range[0] !== 0) {
      previousCell.end = Object.assign({}, getPoint(context.events, range[0]));
      map2.add(range[0], 0, [["exit", previousCell, context]]);
    }
    const now = getPoint(context.events, range[1]);
    previousCell = {
      type: groupName,
      start: Object.assign({}, now),
      // Note: correct end is set later.
      end: Object.assign({}, now)
    };
    map2.add(range[1], 0, [["enter", previousCell, context]]);
    if (range[2] !== 0) {
      const relatedStart = getPoint(context.events, range[2]);
      const relatedEnd = getPoint(context.events, range[3]);
      const valueToken = {
        type: valueName,
        start: Object.assign({}, relatedStart),
        end: Object.assign({}, relatedEnd)
      };
      map2.add(range[2], 0, [["enter", valueToken, context]]);
      if (rowKind !== 2) {
        const start = context.events[range[2]];
        const end = context.events[range[3]];
        start[1].end = Object.assign({}, end[1].end);
        start[1].type = "chunkText";
        start[1].contentType = "text";
        if (range[3] > range[2] + 1) {
          const a = range[2] + 1;
          const b = range[3] - range[2] - 1;
          map2.add(a, b, []);
        }
      }
      map2.add(range[3] + 1, 0, [["exit", valueToken, context]]);
    }
    if (rowEnd !== void 0) {
      previousCell.end = Object.assign({}, getPoint(context.events, rowEnd));
      map2.add(rowEnd, 0, [["exit", previousCell, context]]);
      previousCell = void 0;
    }
    return previousCell;
  }
  function flushTableEnd(map2, context, index2, table2, tableBody) {
    const exits = [];
    const related = getPoint(context.events, index2);
    if (tableBody) {
      tableBody.end = Object.assign({}, related);
      exits.push(["exit", tableBody, context]);
    }
    table2.end = Object.assign({}, related);
    exits.push(["exit", table2, context]);
    map2.add(index2 + 1, 0, exits);
  }
  function getPoint(events, index2) {
    const event = events[index2];
    const side = event[0] === "enter" ? "start" : "end";
    return event[1][side];
  }
  const tasklistCheck = {
    name: "tasklistCheck",
    tokenize: tokenizeTasklistCheck
  };
  function gfmTaskListItem() {
    return {
      text: {
        [91]: tasklistCheck
      }
    };
  }
  function tokenizeTasklistCheck(effects, ok2, nok) {
    const self2 = this;
    return open;
    function open(code2) {
      if (
        // Exit if there’s stuff before.
        self2.previous !== null || // Exit if not in the first content that is the first child of a list
        // item.
        !self2._gfmTasklistFirstContentOfListItem
      ) {
        return nok(code2);
      }
      effects.enter("taskListCheck");
      effects.enter("taskListCheckMarker");
      effects.consume(code2);
      effects.exit("taskListCheckMarker");
      return inside;
    }
    function inside(code2) {
      if (markdownLineEndingOrSpace(code2)) {
        effects.enter("taskListCheckValueUnchecked");
        effects.consume(code2);
        effects.exit("taskListCheckValueUnchecked");
        return close;
      }
      if (code2 === 88 || code2 === 120) {
        effects.enter("taskListCheckValueChecked");
        effects.consume(code2);
        effects.exit("taskListCheckValueChecked");
        return close;
      }
      return nok(code2);
    }
    function close(code2) {
      if (code2 === 93) {
        effects.enter("taskListCheckMarker");
        effects.consume(code2);
        effects.exit("taskListCheckMarker");
        effects.exit("taskListCheck");
        return after;
      }
      return nok(code2);
    }
    function after(code2) {
      if (markdownLineEnding(code2)) {
        return ok2(code2);
      }
      if (markdownSpace(code2)) {
        return effects.check({
          tokenize: spaceThenNonSpace
        }, ok2, nok)(code2);
      }
      return nok(code2);
    }
  }
  function spaceThenNonSpace(effects, ok2, nok) {
    return factorySpace(effects, after, "whitespace");
    function after(code2) {
      return code2 === null ? nok(code2) : ok2(code2);
    }
  }
  function gfm(options) {
    return combineExtensions([
      gfmAutolinkLiteral(),
      gfmFootnote(),
      gfmStrikethrough(options),
      gfmTable(),
      gfmTaskListItem()
    ]);
  }
  const emptyOptions = {};
  function remarkGfm(options) {
    const self2 = (
      /** @type {Processor<Root>} */
      this
    );
    const settings = options || emptyOptions;
    const data = self2.data();
    const micromarkExtensions = data.micromarkExtensions || (data.micromarkExtensions = []);
    const fromMarkdownExtensions = data.fromMarkdownExtensions || (data.fromMarkdownExtensions = []);
    const toMarkdownExtensions = data.toMarkdownExtensions || (data.toMarkdownExtensions = []);
    micromarkExtensions.push(gfm(settings));
    fromMarkdownExtensions.push(gfmFromMarkdown());
    toMarkdownExtensions.push(gfmToMarkdown(settings));
  }
  function CodeBlock({ children }) {
    var _a, _b;
    const [copied, setCopied] = reactExports.useState(false);
    const child = reactExports.Children.only(children);
    if (!reactExports.isValidElement(child)) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { children });
    }
    const language = (_b = (_a = child.props.className) == null ? void 0 : _a.match(/language-([\w-]+)/)) == null ? void 0 : _b[1];
    const code2 = String(child.props.children || "").replace(/\n$/, "");
    const copy = async () => {
      var _a2;
      await ((_a2 = navigator.clipboard) == null ? void 0 : _a2.writeText(code2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    };
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "agui-code-block", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "agui-code-toolbar", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { children: language || "text" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center rounded border-0 bg-transparent p-0 hover:bg-white/10", onClick: () => void copy(), "aria-label": "复制代码", title: "复制代码", children: copied ? /* @__PURE__ */ jsxRuntimeExports.jsx(Check, { className: "size-3.5" }) : /* @__PURE__ */ jsxRuntimeExports.jsx(Copy, { className: "size-3.5" }) })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { children: child })
    ] });
  }
  function Markdown({ children }) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "agui-markdown text-sm leading-6 text-secondary", children: /* @__PURE__ */ jsxRuntimeExports.jsx(
      Markdown$1,
      {
        remarkPlugins: [remarkGfm],
        components: {
          pre: CodeBlock,
          a({ href, children: linkChildren, ...rest }) {
            const external = !!href && /^(https?:)?\/\//i.test(href);
            return /* @__PURE__ */ jsxRuntimeExports.jsx(
              "a",
              {
                ...rest,
                href,
                target: external ? "_blank" : void 0,
                rel: external ? "noopener noreferrer" : void 0,
                children: linkChildren
              }
            );
          }
        },
        children
      }
    ) });
  }
  function statusIcon(status) {
    if (status === "running") return /* @__PURE__ */ jsxRuntimeExports.jsx(LoaderCircle, { className: "size-3 animate-spin" });
    if (status === "ok") return /* @__PURE__ */ jsxRuntimeExports.jsx(CircleCheck, { className: "size-3" });
    if (status === "error" || status === "cancelled") return /* @__PURE__ */ jsxRuntimeExports.jsx(CircleAlert, { className: "size-3" });
    return /* @__PURE__ */ jsxRuntimeExports.jsx(Clock3, { className: "size-3" });
  }
  function statusClass(status) {
    if (status === "ok") return "border-positive/30 bg-positive/10 text-positive";
    if (status === "error" || status === "cancelled") return "border-destructive/35 bg-destructive/10 text-destructive";
    if (status === "needs_confirmation") return "border-warning/35 bg-warning/10 text-warning";
    return "border-primary/15 bg-accent text-muted";
  }
  function statusLabel(status) {
    if (status === "running") return "执行中";
    if (status === "ok") return "已完成";
    if (status === "error") return "出错";
    if (status === "cancelled") return "已取消";
    if (status === "needs_confirmation") return "待确认";
    return "等待中";
  }
  function RelationSearchCard({
    tool,
    result,
    labels,
    hostState,
    running,
    onSelect
  }) {
    const [selectedIds, setSelectedIds] = reactExports.useState([]);
    const stale = result.snapshotId !== hostState.snapshotId || result.hostRevision !== hostState.hostRevision;
    const multiple = result.fieldType === "many2many";
    const compatible = (candidate) => result.relationOperation === "link" ? !candidate.selected : result.relationOperation === "unlink" ? candidate.selected : true;
    reactExports.useEffect(() => setSelectedIds([]), [result.snapshotId, result.hostRevision, result.query]);
    const toggle = (candidate) => {
      setSelectedIds((current) => current.includes(candidate.id) ? current.filter((id) => id !== candidate.id) : [...current, candidate.id]);
    };
    const selected = result.candidates.filter((candidate) => selectedIds.includes(candidate.id));
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rounded-lg border border-border bg-background-secondary/80 p-3", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex items-center justify-between gap-3", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "min-w-0", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "truncate text-xs font-semibold text-primary", children: result.fieldLabel || result.field }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-0.5 truncate text-[11px] text-muted", children: [
            labels.relationCandidates,
            " · ",
            result.relation
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0 rounded border border-border bg-background px-2 py-1 text-[10px] text-muted", children: result.query })
      ] }),
      stale ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-3 rounded border border-warning/30 bg-warning/10 p-2 text-xs text-warning", children: labels.relationSelectionExpired }) : null,
      !result.candidates.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-3 text-xs text-muted", children: labels.relationNoResults }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-3 grid gap-1.5", children: result.candidates.map((candidate) => {
        const disabled = stale || running || !compatible(candidate);
        return multiple ? /* @__PURE__ */ jsxRuntimeExports.jsxs("label", { className: "flex min-h-9 items-center gap-2 rounded border border-border bg-background px-2.5 py-1.5 text-xs text-primary has-[:disabled]:opacity-45", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("input", { type: "checkbox", className: "size-4", disabled, checked: selectedIds.includes(candidate.id), onChange: () => toggle(candidate) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "min-w-0 flex-1 truncate", children: candidate.displayName }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "shrink-0 text-[10px] text-muted", children: [
            "#",
            candidate.id
          ] })
        ] }, candidate.id) : /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { type: "button", disabled, className: "flex min-h-9 items-center gap-2 rounded border border-solid border-border bg-background px-2.5 py-1.5 text-left text-xs text-primary hover:bg-accent disabled:opacity-45", onClick: () => onSelect(tool, [candidate]), children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "min-w-0 flex-1 truncate", children: candidate.displayName }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "shrink-0 text-[10px] text-muted", children: [
            "#",
            candidate.id
          ] })
        ] }, candidate.id);
      }) }),
      multiple && result.candidates.length ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-3 flex items-center justify-between gap-3", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "text-[11px] text-muted", children: labels.selectedRelationCount.replace("{count}", String(selected.length)) }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", disabled: stale || running || !selected.length, className: "h-8 rounded-md border border-solid border-primary bg-primary px-3 text-xs text-primaryAccent disabled:opacity-40", onClick: () => onSelect(tool, selected), children: labels.confirmRelationSelection })
      ] }) : null
    ] });
  }
  function RecordCandidatesCard({
    tool,
    result,
    hostState,
    running,
    onSelect
  }) {
    const stale = result.snapshotId !== hostState.snapshotId || result.hostRevision !== hostState.hostRevision;
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "rounded-lg border border-border bg-background-secondary/80 p-3", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex items-center justify-between gap-3", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "min-w-0", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "truncate text-xs font-semibold text-primary", children: result.label }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-0.5 text-[11px] text-muted", children: [
            "匹配 ",
            result.count,
            " 条记录"
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0 rounded border border-border bg-background px-2 py-1 text-[10px] text-muted", children: "选择记录" })
      ] }),
      stale ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-3 rounded border border-warning/30 bg-warning/10 p-2 text-xs text-warning", children: "候选快照已过期，请重新筛选。" }) : null,
      !result.candidates.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-3 text-xs text-muted", children: "没有可选择的可见记录。" }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-3 grid gap-1.5", children: result.candidates.map((candidate) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { type: "button", disabled: stale || running, className: "flex min-h-9 items-center gap-2 rounded border border-solid border-border bg-background px-2.5 py-1.5 text-left text-xs text-primary hover:bg-accent disabled:opacity-45", onClick: () => onSelect(tool, candidate), children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "min-w-0 flex-1 truncate", children: candidate.displayName }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(ChevronRight, { className: "size-3.5 shrink-0 text-muted" })
      ] }, candidate.token)) })
    ] });
  }
  function displayDiffValue(value) {
    if (value === false || value === null || value === void 0 || value === "") return "空";
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  }
  function ConfirmationPreview({ result }) {
    const preview = result.preview && typeof result.preview === "object" ? result.preview : {};
    const changes = Array.isArray(preview.changes) ? preview.changes : [];
    const riskLabels = {
      multiple_fields: "多字段修改",
      relation_field: "关系字段",
      policy_high_risk_field: "管理员标记字段",
      field_type_unknown: "字段类型未确认",
      destructive_command: "写入操作",
      object_button: "对象按钮"
    };
    const reasons = Array.isArray(preview.riskReasons) ? preview.riskReasons : [];
    const control = preview.control && typeof preview.control === "object" ? preview.control : null;
    if (control) {
      return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-2 rounded border border-warning/25 bg-background p-2 text-xs text-primary", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "font-semibold", children: String(control.label || "对象按钮") }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-1 text-muted", children: [
          "所属记录：",
          String(control.recordLabel || "当前记录")
        ] })
      ] });
    }
    if (!changes.length) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "mt-2 max-h-52 overflow-auto rounded bg-background p-2 text-[11px]", children: JSON.stringify({ target: result.target || {}, patch: result.patch || {} }, null, 2) });
    }
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-2 overflow-hidden rounded border border-warning/25 bg-background text-primary", children: [
      changes.map((change) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "grid gap-1 border-b border-border p-2 last:border-b-0", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-[11px] font-semibold", children: String(change.label || change.field) }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-2 text-[11px]", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "break-words text-muted", children: displayDiffValue(change.oldValue) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx(ChevronRight, { className: "mt-0.5 size-3 text-muted" }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "break-words", children: displayDiffValue(change.newValue) })
        ] })
      ] }, String(change.field))),
      reasons.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex flex-wrap gap-1 border-t border-warning/20 p-2", children: reasons.map((reason) => /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "rounded border border-warning/25 px-1.5 py-0.5 text-[10px] text-warning", children: riskLabels[String(reason)] || String(reason) }, String(reason))) }) : null
    ] });
  }
  function ToolCard({ tool, onConfirm, onUndo, labels, running }) {
    const names = {
      "odoo.open_menu": "打开菜单",
      "odoo.apply_filter": "筛选当前视图",
      "odoo.open_record": "打开记录",
      "odoo.open_create": "新建记录",
      "odoo.enter_edit_mode": "进入编辑模式",
      "odoo.activate_view_control": "激活页面控件",
      "odoo.search_relation": "查询关系记录",
      "odoo.stage_current_form": "暂存当前表单",
      "odoo.patch_current_form": "修改当前表单",
      "odoo.validate_current_form": "校验当前表单",
      "odoo.save_current_form": "保存当前表单",
      "odoo.discard_current_form": "放弃表单更改"
    };
    const displayName = names[toolName(tool)] || toolName(tool);
    const result = tool.result && typeof tool.result === "object" ? tool.result : {};
    const applied = Array.isArray(result.applied) ? result.applied.length : 0;
    const rejected = Array.isArray(result.rejected) ? result.rejected.length : 0;
    const status = tool.status || "pending";
    const receipt = result.receipt && typeof result.receipt === "object" ? result.receipt : {};
    const undo = receipt.undo && typeof receipt.undo === "object" ? receipt.undo : {};
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("details", { open: status === "needs_confirmation" || !!tool.needs_confirmation || void 0, className: "rounded-lg border border-border bg-background-secondary/80 p-2", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsxs("summary", { className: "flex cursor-pointer list-none flex-wrap items-center gap-2", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "inline-flex items-center gap-1.5 rounded-md bg-background px-2 py-1 font-mono text-[11px] text-primary", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(Hammer, { className: "size-3" }),
          displayName
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: cn("inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] uppercase", statusClass(status)), children: [
          statusIcon(status),
          statusLabel(status)
        ] }),
        applied || rejected ? /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "rounded-md bg-background px-2 py-1 text-[11px] text-muted", children: [
          "已应用 ",
          applied,
          " 项 / 已拒绝 ",
          rejected,
          " 项"
        ] }) : null
      ] }),
      tool.error || result.error ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-2 rounded-md border border-destructive/25 bg-destructive/10 p-2 text-xs text-destructive", children: String(tool.error || result.error) }) : null,
      status === "needs_confirmation" || tool.needs_confirmation ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-2 rounded-md border border-solid border-warning/25 bg-warning/10 p-2 text-xs text-warning", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { children: [
          "需要确认：",
          displayName
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx(ConfirmationPreview, { result }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-2 flex gap-2", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", disabled: running, className: "rounded-md border border-solid border-primary bg-primary px-2 py-1 text-primaryAccent disabled:opacity-45", onClick: () => onConfirm(true), children: labels.approve }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", disabled: running, className: "rounded-md border border-solid border-border bg-background-panel px-2 py-1 disabled:opacity-45", onClick: () => onConfirm(false), children: labels.reject })
        ] })
      ] }) : null,
      undo.available ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-2 flex items-center gap-2 border-t border-border pt-2", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { type: "button", disabled: running || undo.status === "running" || undo.status === "undone", title: "撤销本次修改", className: "inline-flex h-8 items-center gap-1.5 rounded-md border border-solid border-border bg-background px-2.5 text-xs text-primary hover:bg-accent disabled:opacity-45", onClick: onUndo, children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx(RotateCcw, { className: "size-3.5" }),
          undo.status === "running" ? "撤销中" : undo.status === "undone" ? "已撤销" : "撤销"
        ] }),
        undo.error ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "text-xs text-destructive", children: String(undo.error) }) : null
      ] }) : null,
      /* @__PURE__ */ jsxRuntimeExports.jsxs("details", { className: "mt-2 border-t border-border pt-2", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("summary", { className: "cursor-pointer text-xs text-muted", children: "查看详情" }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mt-2 grid gap-2 md:grid-cols-2", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "max-h-52 overflow-auto rounded-md bg-background p-2 text-[11px] text-muted", children: JSON.stringify({ id: toolCallId(tool), args: toolArgs(tool) }, null, 2) }),
          /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "max-h-52 overflow-auto rounded-md bg-background p-2 text-[11px] text-muted", children: JSON.stringify(tool.result || null, null, 2) })
        ] })
      ] })
    ] });
  }
  class ToolRendererBoundary extends React.Component {
    constructor() {
      super(...arguments);
      __publicField(this, "state", { failed: false });
    }
    static getDerivedStateFromError() {
      return { failed: true };
    }
    render() {
      return this.state.failed ? this.props.fallback : this.props.children;
    }
  }
  function RenderTool({ tool, renderers, onConfirm, onUndo, labels, hostState, running, onSelectRelation, onSelectRecord }) {
    const Renderer = renderers == null ? void 0 : renderers[toolName(tool)];
    const fallback = /* @__PURE__ */ jsxRuntimeExports.jsx(ToolCard, { tool, onConfirm, onUndo, labels, running });
    if (Renderer) return /* @__PURE__ */ jsxRuntimeExports.jsx(ToolRendererBoundary, { fallback, children: /* @__PURE__ */ jsxRuntimeExports.jsx(Renderer, { tool }) });
    const result = tool.result && typeof tool.result === "object" ? tool.result : null;
    if (toolName(tool) === "odoo.search_relation" && (result == null ? void 0 : result.ok) && Array.isArray(result.candidates)) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(RelationSearchCard, { tool, result, labels, hostState, running, onSelect: onSelectRelation });
    }
    if (toolName(tool) === "odoo.apply_filter" && (result == null ? void 0 : result.ok) && Array.isArray(result.candidates)) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx(RecordCandidatesCard, { tool, result, hostState, running, onSelect: onSelectRecord });
    }
    return fallback;
  }
  function Reasoning({ steps }) {
    if (!steps.length) return null;
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex items-start gap-3", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(Workflow, { className: "mt-0.5 size-5 shrink-0 text-muted" }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex flex-col gap-2", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-xs font-medium uppercase text-muted", children: "思考过程" }),
        steps.map((step, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("details", { className: "rounded-lg border border-border bg-accent px-3 py-2 text-sm", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("summary", { className: "cursor-pointer text-xs text-primary", children: [
            "步骤 ",
            index2 + 1,
            "：",
            step.title
          ] }),
          step.content ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-2 text-xs leading-5 text-muted", children: step.content }) : null
        ] }, `${step.title}-${index2}`))
      ] })
    ] });
  }
  function References({ references }) {
    const groups = normalizeReferenceGroups(references);
    if (!groups.length) return null;
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex flex-col gap-3", children: groups.map((group, groupIndex) => /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex flex-wrap gap-2", children: group.references.map((reference, index2) => {
      const body = /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "h-20 w-48 overflow-hidden rounded-lg border border-border bg-accent p-3 hover:bg-background-secondary", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "truncate text-sm font-medium text-primary", children: reference.name }),
        reference.content ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-2 line-clamp-2 text-xs leading-4 text-muted", children: reference.content }) : null
      ] });
      return reference.url ? /* @__PURE__ */ jsxRuntimeExports.jsx("a", { href: reference.url, target: "_blank", rel: "noopener noreferrer", children: body }, `${reference.name}-${index2}`) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { children: body }, `${reference.name}-${index2}`);
    }) }, `${group.query || "references"}-${groupIndex}`)) });
  }
  function attachmentUrl$1(attachment) {
    return `/agui_chat/attachment/${encodeURIComponent(attachment.id)}`;
  }
  function attachmentMeta(attachment) {
    var _a;
    const type = attachment.mimeType.includes("pdf") ? "PDF" : ((_a = attachment.mimeType.split("/").pop()) == null ? void 0 : _a.toUpperCase()) || "文件";
    const size = attachment.size < 1024 * 1024 ? `${Math.max(1, Math.round(attachment.size / 1024))} KB` : `${(attachment.size / (1024 * 1024)).toFixed(2)} MB`;
    return `${type} 文档 · ${size}`;
  }
  function Attachments({ attachments, labels, onPreview }) {
    if (!(attachments == null ? void 0 : attachments.length)) return null;
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex flex-wrap justify-end gap-2", children: attachments.map((attachment) => attachment.modality === "image" ? /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "border-0 bg-transparent p-0", "aria-label": `${labels.filePreview}: ${attachment.name}`, onClick: () => onPreview(attachment), children: /* @__PURE__ */ jsxRuntimeExports.jsx("img", { className: "h-28 w-40 rounded-lg border border-border object-cover", src: attachmentUrl$1(attachment), alt: attachment.name }) }, attachment.id) : /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { type: "button", className: "flex h-14 w-60 max-w-full items-center gap-2 rounded-lg border border-solid border-border bg-background-panel px-2.5 text-left text-xs text-primary hover:bg-background-secondary", "aria-label": `${labels.filePreview}: ${attachment.name}`, onClick: () => onPreview(attachment), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "grid size-7 shrink-0 place-items-center rounded bg-background-secondary", children: /* @__PURE__ */ jsxRuntimeExports.jsx(FileText, { className: "size-4" }) }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "min-w-0 flex-1", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block truncate", children: attachment.name }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "mt-0.5 block truncate text-[11px] text-muted", children: attachmentMeta(attachment) })
      ] }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(ChevronRight, { className: "size-4 shrink-0 text-muted" })
    ] }, attachment.id)) });
  }
  function DefaultAssistantMessage({
    message,
    running,
    isCurrent,
    toolRenderers,
    labels,
    icons,
    hostState,
    onCopy,
    onRegenerate,
    onConfirmTool,
    onUndoTool = () => void 0,
    onSelectRelation,
    onSelectRecord
  }) {
    var _a, _b, _c;
    const [copied, setCopied] = reactExports.useState(false);
    const content2 = asText(message.content);
    const reasoning = ((_a = message.extra_data) == null ? void 0 : _a.reasoning_steps) || [];
    const references = ((_b = message.extra_data) == null ? void 0 : _b.references) || [];
    const copy = async () => {
      await onCopy();
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    };
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex flex-col gap-5", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(Reasoning, { steps: reasoning }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(References, { references }),
      ((_c = message.tool_calls) == null ? void 0 : _c.length) ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex flex-col gap-2", children: message.tool_calls.map((tool, index2) => /* @__PURE__ */ jsxRuntimeExports.jsx(RenderTool, { tool, renderers: toolRenderers, labels, hostState, running, onSelectRelation, onSelectRecord, onConfirm: (approved) => onConfirmTool(tool, approved), onUndo: () => onUndoTool(tool) }, tool.key || toolCallId(tool) || `${toolName(tool)}-${index2}`)) }) : null,
      content2 || message.streaming_error ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "group flex items-start gap-3", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "grid size-6 shrink-0 place-items-center rounded bg-primary text-primaryAccent", children: icons.assistant }),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "min-w-0 flex-1", children: [
          message.streaming_error ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive", children: message.streaming_error }) : null,
          content2 ? /* @__PURE__ */ jsxRuntimeExports.jsx(Markdown, { children: content2 }) : null,
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: cn(
            "agui-message-controls mt-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100",
            isCurrent && "opacity-100"
          ), children: [
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center rounded border-0 bg-transparent p-0 text-muted hover:bg-accent hover:text-primary", "aria-label": copied ? labels.copied : labels.copyResponse, title: labels.copyResponse, onClick: () => void copy(), children: copied ? icons.complete : icons.copy }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center rounded border-0 bg-transparent p-0 text-muted hover:bg-accent hover:text-primary disabled:opacity-40", disabled: running, "aria-label": labels.regenerateResponse, title: labels.regenerateResponse, onClick: onRegenerate, children: icons.regenerate })
          ] })
        ] })
      ] }) : null
    ] });
  }
  function DefaultUserMessage({ message, labels, onPreviewAttachment, onRemoveMenuMention, onRemoveMention }) {
    var _a, _b, _c;
    const mention = message.menuMention;
    const actionLabels = {
      read: "引用数据",
      open: "打开",
      create: "新建",
      view: "查看",
      edit: "编辑",
      apply: "应用"
    };
    const mentionIcon2 = (kind) => {
      if (kind === "menu") return /* @__PURE__ */ jsxRuntimeExports.jsx(Menu, { className: "size-3.5 shrink-0" });
      if (kind === "record") return /* @__PURE__ */ jsxRuntimeExports.jsx(Database, { className: "size-3.5 shrink-0" });
      if (kind === "saved_filter") return /* @__PURE__ */ jsxRuntimeExports.jsx(Filter, { className: "size-3.5 shrink-0" });
      return /* @__PURE__ */ jsxRuntimeExports.jsx(SlidersHorizontal, { className: "size-3.5 shrink-0" });
    };
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex w-full justify-end", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "min-w-0 max-w-[82%]", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(Attachments, { attachments: message.attachments, labels, onPreview: onPreviewAttachment }),
      ((_a = message.mentions) == null ? void 0 : _a.length) ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex flex-wrap justify-end gap-1.5", children: message.mentions.map((reference) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: cn(
        "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
        reference.valid ? "border-primary/20 bg-accent text-primary" : "border-warning/35 bg-warning/10 text-warning"
      ), title: reference.detail, children: [
        mentionIcon2(reference.kind),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "truncate", children: reference.label }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0 opacity-70", children: actionLabels[reference.action] }),
        !reference.valid ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0", children: "（已失效）" }) : null,
        onRemoveMention ? /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-5 shrink-0 place-items-center rounded border-0 bg-transparent p-0 text-current opacity-65 hover:bg-background hover:opacity-100", "aria-label": `移除引用 ${reference.label}`, title: "移除引用", onClick: () => onRemoveMention(reference.id), children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3" }) }) : null
      ] }, reference.id)) }) : null,
      ((_b = message.workspaceReferences) == null ? void 0 : _b.length) ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex flex-wrap justify-end gap-1.5", "aria-label": "消息工作区引用", children: message.workspaceReferences.map((reference) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border border-border bg-background-panel px-2 py-1 text-xs text-primary", title: reference.path, children: [
        reference.isDirectory ? /* @__PURE__ */ jsxRuntimeExports.jsx(Folder, { className: "size-3.5 shrink-0" }) : /* @__PURE__ */ jsxRuntimeExports.jsx(FileText, { className: "size-3.5 shrink-0" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "truncate", children: reference.name })
      ] }, reference.id)) }) : null,
      ((_c = message.skills) == null ? void 0 : _c.length) ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex flex-wrap justify-end gap-1.5", "aria-label": "消息技能", children: message.skills.map((skill) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: cn(
        "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
        skill.valid ? "border-emerald-700/20 bg-emerald-50 text-emerald-900" : "border-warning/35 bg-warning/10 text-warning"
      ), title: skill.description, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(Sparkles, { className: "size-3.5 shrink-0" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "truncate", children: skill.name }),
        !skill.valid ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0", children: "（已失效）" }) : null
      ] }, skill.id)) }) : null,
      mention ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mb-2 flex justify-end", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
        mention.valid ? "border-primary/20 bg-accent text-primary" : "border-warning/35 bg-warning/10 text-warning"
      ), title: mention.fullPath, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(AtSign, { className: "size-3.5 shrink-0" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "truncate", children: mention.fullPath }),
        !mention.valid ? /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0", children: "（已失效）" }) : null,
        onRemoveMenuMention ? /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-5 shrink-0 place-items-center rounded border-0 bg-transparent p-0 text-current opacity-65 hover:bg-background hover:opacity-100", "aria-label": "移除菜单", title: "移除菜单", onClick: onRemoveMenuMention, children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3" }) }) : null
      ] }) }) : null,
      asText(message.content) ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "ml-auto w-fit rounded-lg bg-background-secondary px-3.5 py-2 text-sm leading-6 text-secondary", children: asText(message.content) }) : null
    ] }) });
  }
  function Suggestions({ suggestions, disabled, onSelect }) {
    if (!(suggestions == null ? void 0 : suggestions.length)) return null;
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex flex-wrap justify-center gap-2", children: suggestions.map((suggestion) => /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { type: "button", disabled, className: "max-w-64 rounded-lg border border-solid border-border bg-background-secondary px-3 py-2 text-left hover:bg-accent disabled:opacity-40", onClick: () => onSelect(suggestion), children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-xs font-medium text-primary", children: suggestion.title }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-1 line-clamp-2 text-xs text-muted", children: suggestion.message })
    ] }, `${suggestion.title}-${suggestion.message}`)) });
  }
  function Messages({
    messages,
    running,
    suggestions,
    toolRenderers,
    labels,
    icons,
    components,
    onRegenerate,
    onSuggestion,
    onConfirmTool,
    onUndoTool,
    onCopy,
    onFeedback,
    onPreviewAttachment,
    hostState,
    onSelectRelation,
    onSelectRecord,
    onRemoveMenuMention,
    onRemoveMention
  }) {
    const [feedback, setFeedback] = reactExports.useState({});
    const displayMessages = visibleMessages(messages);
    const lastAssistantIndex = displayMessages.reduce(
      (last, message, index2) => message.role === "assistant" || message.role === "agent" ? index2 : last,
      -1
    );
    const AssistantMessage = (components == null ? void 0 : components.AssistantMessage) || DefaultAssistantMessage;
    const UserMessage = (components == null ? void 0 : components.UserMessage) || DefaultUserMessage;
    if (!displayMessages.length) return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex min-h-[320px] flex-col items-center justify-center px-4 text-center", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "grid size-12 place-items-center rounded-xl bg-accent text-primary", children: icons.assistant }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-4 text-sm font-medium text-primary", children: labels.emptyTitle }),
      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mt-1 mb-5 max-w-sm text-sm text-muted", children: labels.emptyDescription }),
      /* @__PURE__ */ jsxRuntimeExports.jsx(Suggestions, { suggestions, disabled: running, onSelect: onSuggestion })
    ] });
    return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "mx-auto flex w-full max-w-3xl flex-col gap-12 px-4 py-8", children: [
      displayMessages.map((message, index2) => {
        var _a;
        const role = message.role === "agent" ? "assistant" : message.role;
        if (role === "assistant") return /* @__PURE__ */ jsxRuntimeExports.jsx(AssistantMessage, { message, running, isCurrent: index2 === lastAssistantIndex, toolRenderers, labels, icons, feedback: feedback[message.id] || null, hostState, onSelectRelation: (tool, candidates) => onSelectRelation(tool, candidates), onSelectRecord: (tool, candidate) => onSelectRecord(tool, candidate), onCopy: () => onCopy(message), onRegenerate: () => onRegenerate(message.id), onFeedback: (next) => {
          const value = feedback[message.id] === next ? null : next;
          setFeedback((current) => ({ ...current, [message.id]: value }));
          onFeedback(message, value);
        }, onConfirmTool, onUndoTool: (tool) => onUndoTool == null ? void 0 : onUndoTool(tool) }, message.id || `assistant-${index2}`);
        if (role === "user") return /* @__PURE__ */ jsxRuntimeExports.jsx(UserMessage, { message, icons, labels, onPreviewAttachment, onRemoveMenuMention: message.menuMention && onRemoveMenuMention ? () => onRemoveMenuMention(message.id) : void 0, onRemoveMention: ((_a = message.mentions) == null ? void 0 : _a.length) && onRemoveMention ? (referenceId) => onRemoveMention(message.id, referenceId) : void 0 }, message.id || `user-${index2}`);
        return null;
      }),
      running ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "agui-activity flex items-center gap-1.5 py-1", "aria-label": labels.generatingResponse, children: [0, 1, 2].map((index2) => /* @__PURE__ */ jsxRuntimeExports.jsx(React.Fragment, { children: icons.activity }, index2)) }) : /* @__PURE__ */ jsxRuntimeExports.jsx(Suggestions, { suggestions, disabled: false, onSelect: onSuggestion })
    ] });
  }
  const DEFAULT_WIDTH = 620;
  const MIN_WIDTH = 360;
  const MAX_WIDTH = 920;
  const MIN_MAIN_WIDTH = 420;
  const KEYBOARD_STEP = 24;
  function AsidePanel({
    ariaLabel,
    eyebrow,
    title,
    icon,
    actions,
    closeLabel,
    resizeLabel = "调整侧栏宽度",
    onClose,
    children,
    className = "",
    defaultWidth = DEFAULT_WIDTH,
    minWidth = MIN_WIDTH,
    maxWidth = MAX_WIDTH,
    minMainWidth = MIN_MAIN_WIDTH
  }) {
    const panelRef = reactExports.useRef(null);
    const [width, setWidth] = reactExports.useState(defaultWidth);
    const clampWidth = reactExports.useCallback((nextWidth) => {
      const panel = panelRef.current;
      let main = panel == null ? void 0 : panel.previousElementSibling;
      while (main == null ? void 0 : main.classList.contains("agui-aside-backdrop")) main = main.previousElementSibling;
      const available = main instanceof HTMLElement && panel ? main.getBoundingClientRect().width + panel.getBoundingClientRect().width : Number.POSITIVE_INFINITY;
      const availableMax = Math.max(minWidth, available - minMainWidth);
      return Math.min(Math.max(nextWidth, minWidth), maxWidth, availableMax);
    }, [maxWidth, minMainWidth, minWidth]);
    reactExports.useEffect(() => {
      const closeOnEscape = (event) => {
        if (event.key === "Escape") onClose();
      };
      window.addEventListener("keydown", closeOnEscape);
      return () => window.removeEventListener("keydown", closeOnEscape);
    }, [onClose]);
    const handleResizeStart = reactExports.useCallback((event) => {
      var _a;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = ((_a = panelRef.current) == null ? void 0 : _a.getBoundingClientRect().width) || width;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      const handlePointerMove = (moveEvent) => {
        setWidth(clampWidth(startWidth + startX - moveEvent.clientX));
      };
      const handlePointerUp = () => {
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
      };
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp, { once: true });
    }, [clampWidth, width]);
    const style = { "--agui-aside-width": `${width}px` };
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "agui-aside-backdrop", "aria-label": closeLabel, onClick: onClose }),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("aside", { ref: panelRef, className: `agui-aside ${className}`.trim(), style, "aria-label": ariaLabel, children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "button",
          {
            type: "button",
            className: "agui-aside-resize",
            "aria-label": resizeLabel,
            onPointerDown: handleResizeStart,
            onKeyDown: (event) => {
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                setWidth((current) => clampWidth(current + KEYBOARD_STEP));
              } else if (event.key === "ArrowRight") {
                event.preventDefault();
                setWidth((current) => clampWidth(current - KEYBOARD_STEP));
              }
            },
            children: /* @__PURE__ */ jsxRuntimeExports.jsx(GripVertical, { size: 16, strokeWidth: 1.8 })
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsxs("header", { className: "agui-aside-head", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "agui-aside-title", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { children: [
              icon,
              eyebrow
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { title, children: title })
          ] }),
          /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "agui-aside-actions", children: [
            actions,
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", "aria-label": closeLabel, title: closeLabel, onClick: onClose, children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { size: 16 }) })
          ] })
        ] }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "agui-aside-body", children })
      ] })
    ] });
  }
  const SCRIPT_URL = "/agui_chat/static/lib/agui-chat-react/agui_file_viewer.12.0.8.4.0.js";
  let viewerModulePromise;
  function loadProductionBundle() {
    var _a;
    if ((_a = window.AguiFileViewerBundle) == null ? void 0 : _a.FileViewer) return Promise.resolve(window.AguiFileViewerBundle);
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${SCRIPT_URL}"]`);
      const script = existing || document.createElement("script");
      const handleLoad = () => {
        var _a2;
        return ((_a2 = window.AguiFileViewerBundle) == null ? void 0 : _a2.FileViewer) ? resolve(window.AguiFileViewerBundle) : reject(new Error("文件查看器资源未正确注册"));
      };
      const handleError = () => reject(new Error("无法加载文件查看器资源"));
      script.addEventListener("load", handleLoad, { once: true });
      script.addEventListener("error", handleError, { once: true });
      if (!existing) {
        script.src = SCRIPT_URL;
        script.async = true;
        document.head.appendChild(script);
      }
    });
  }
  function loadFileViewer() {
    var _a;
    if (!viewerModulePromise) {
      viewerModulePromise = ((_a = window.AguiFileViewerBundle) == null ? void 0 : _a.FileViewer) ? Promise.resolve(window.AguiFileViewerBundle) : loadProductionBundle();
      viewerModulePromise.catch(() => {
        viewerModulePromise = void 0;
      });
    }
    return viewerModulePromise;
  }
  function LazyFileViewer({ errorLabel, ...props }) {
    const [Viewer, setViewer] = reactExports.useState(null);
    const [failed, setFailed] = reactExports.useState(false);
    reactExports.useEffect(() => {
      let active = true;
      loadFileViewer().then(
        (module) => {
          if (active) setViewer(() => module.FileViewer);
        },
        () => {
          if (active) setFailed(true);
        }
      );
      return () => {
        active = false;
      };
    }, []);
    if (failed) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "agui-file-viewer-state text-sm text-muted", role: "alert", children: errorLabel });
    }
    if (!Viewer) {
      return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "agui-file-viewer-state", "aria-label": "正在加载文件预览", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "agui-activity flex gap-1", "aria-hidden": "true", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "agui-activity-dot" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "agui-activity-dot" }),
        /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "agui-activity-dot" })
      ] }) });
    }
    return /* @__PURE__ */ jsxRuntimeExports.jsx(Viewer, { ...props });
  }
  function attachmentUrl(attachment) {
    return `/agui_chat/attachment/${encodeURIComponent(attachment.id)}`;
  }
  function extensionFromName(name2) {
    const cleanName = name2.split(/[?#]/)[0];
    const dotIndex = cleanName.lastIndexOf(".");
    return dotIndex >= 0 && dotIndex < cleanName.length - 1 ? cleanName.slice(dotIndex + 1).toLowerCase() : "";
  }
  function extensionFromMime(mimeType) {
    if (mimeType.includes("pdf")) return "pdf";
    if (mimeType.includes("wordprocessingml")) return "docx";
    if (mimeType.includes("msword")) return "doc";
    if (mimeType.includes("spreadsheetml")) return "xlsx";
    if (mimeType.includes("vnd.ms-excel")) return "xls";
    if (mimeType.includes("presentation") || mimeType.includes("powerpoint")) return "pptx";
    if (mimeType.includes("ofd")) return "ofd";
    if (mimeType.startsWith("image/") || mimeType.startsWith("audio/") || mimeType.startsWith("video/")) {
      return mimeType.split("/")[1] || "";
    }
    if (mimeType.includes("json")) return "json";
    if (mimeType.startsWith("text/")) return mimeType.includes("markdown") ? "md" : "txt";
    return "";
  }
  function getAttachmentPreviewType(attachment) {
    return extensionFromName(attachment.name) || extensionFromMime(attachment.mimeType) || attachment.mimeType;
  }
  function FilePreviewPanel({ attachment, labels, onClose }) {
    const url = attachmentUrl(attachment);
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      AsidePanel,
      {
        className: "agui-file-preview",
        ariaLabel: labels.filePreview,
        eyebrow: labels.filePreview,
        title: attachment.name,
        icon: /* @__PURE__ */ jsxRuntimeExports.jsx(FileText, { size: 13, strokeWidth: 1.8 }),
        closeLabel: labels.closeFilePreview,
        resizeLabel: "调整文件预览宽度",
        onClose,
        actions: /* @__PURE__ */ jsxRuntimeExports.jsx("a", { href: url, target: "_blank", rel: "noopener noreferrer", "aria-label": labels.openFile, title: labels.openFile, children: /* @__PURE__ */ jsxRuntimeExports.jsx(ExternalLink, { size: 16 }) }),
        children: /* @__PURE__ */ jsxRuntimeExports.jsx(
          LazyFileViewer,
          {
            className: "agui-file-viewer",
            errorLabel: labels.previewUnavailable,
            url,
            filename: attachment.name,
            name: attachment.name,
            type: getAttachmentPreviewType(attachment),
            options: { theme: "light", styleIsolation: "shadow" }
          },
          attachment.id
        )
      }
    );
  }
  function formatSessionDate(value) {
    if (!value) {
      return "";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    return date.toLocaleDateString(void 0, {
      month: "short",
      day: "numeric"
    });
  }
  function Sidebar({
    snapshot,
    initialCollapsed,
    onNewSession,
    onRefreshSessions,
    onLoadSession,
    onArchiveSession,
    labels
  }) {
    var _a;
    const [collapsed, setCollapsed] = reactExports.useState(!!initialCollapsed);
    const [confirmArchive, setConfirmArchive] = reactExports.useState(null);
    const currentSessionId = (_a = snapshot.session) == null ? void 0 : _a.id;
    const sortedSessions = reactExports.useMemo(() => snapshot.sessions || [], [snapshot.sessions]);
    return /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
      !collapsed ? /* @__PURE__ */ jsxRuntimeExports.jsx(
        "button",
        {
          type: "button",
          className: "absolute inset-0 z-20 hidden border-0 bg-primary/10 p-0 max-md:block",
          "aria-label": "关闭侧栏",
          onClick: () => setCollapsed(true)
        }
      ) : null,
      collapsed ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            "aria-hidden": "true",
            className: "absolute inset-y-0 left-0 z-10 w-1 border-r border-border bg-accent shadow-[1px_0_0_rgba(15,23,42,0.04)]"
          }
        ),
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          Button,
          {
            variant: "ghost",
            size: "icon",
            className: "absolute left-2 top-2 z-20 size-9 border border-border bg-background-panel text-primary shadow-md transition-colors hover:border-primary/30 hover:bg-accent hover:text-primary focus-visible:ring-2 focus-visible:ring-primary/40",
            onClick: () => setCollapsed(false),
            "aria-label": "展开侧栏",
            title: "展开侧栏",
            children: /* @__PURE__ */ jsxRuntimeExports.jsx(ChevronsRight, { className: "size-4" })
          }
        )
      ] }) : null,
      /* @__PURE__ */ jsxRuntimeExports.jsxs(
        "aside",
        {
          className: cn(
            "relative flex h-full shrink-0 flex-col overflow-hidden border-r border-border bg-background px-2 py-3 transition-[width]",
            collapsed ? "w-0 border-r-0 p-0" : "w-64 max-md:absolute max-md:inset-y-0 max-md:z-30 max-md:shadow-xl"
          ),
          children: [
            !collapsed ? /* @__PURE__ */ jsxRuntimeExports.jsx(
              Button,
              {
                variant: "ghost",
                size: "icon",
                className: "absolute right-1.5 top-2 z-10 size-8 border border-border bg-background-panel text-primary shadow-sm transition-colors hover:border-primary/30 hover:bg-accent hover:text-primary focus-visible:ring-2 focus-visible:ring-primary/40",
                onClick: () => setCollapsed((value) => !value),
                "aria-label": "收起侧栏",
                children: /* @__PURE__ */ jsxRuntimeExports.jsx(ChevronsLeft, { className: "size-4" })
              }
            ) : null,
            /* @__PURE__ */ jsxRuntimeExports.jsxs(
              "div",
              {
                className: cn(
                  "flex min-w-60 flex-col gap-5 transition-opacity",
                  collapsed ? "pointer-events-none opacity-0" : "opacity-100"
                ),
                children: [
                  /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex items-center gap-2 pr-9", children: [
                    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "grid size-7 place-items-center rounded-lg bg-brand text-xs font-semibold text-white", children: "AG" }),
                    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "min-w-0", children: /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "truncate text-xs font-semibold uppercase text-primary", children: "智能助手" }) })
                  ] }),
                  /* @__PURE__ */ jsxRuntimeExports.jsxs(
                    Button,
                    {
                      variant: "primary",
                      className: "h-9 w-full text-xs font-semibold uppercase",
                      onClick: onNewSession,
                      disabled: snapshot.running || snapshot.loadingSessions,
                      children: [
                        /* @__PURE__ */ jsxRuntimeExports.jsx(MessageSquarePlus, { className: "size-4" }),
                        labels.newSession
                      ]
                    }
                  ),
                  /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex flex-col gap-2", children: [
                    /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex items-center justify-between", children: [
                      /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "text-xs font-medium uppercase text-primary", children: "会话" }),
                      /* @__PURE__ */ jsxRuntimeExports.jsx(
                        Button,
                        {
                          variant: "ghost",
                          size: "icon",
                          className: "size-7",
                          onClick: onRefreshSessions,
                          disabled: snapshot.loadingSessions,
                          "aria-label": "刷新会话",
                          children: /* @__PURE__ */ jsxRuntimeExports.jsx(RefreshCw, { className: cn("size-3.5", snapshot.loadingSessions && "animate-spin") })
                        }
                      )
                    ] }),
                    /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "max-h-[calc(100vh-235px)] min-h-32 overflow-y-auto pr-1", children: sortedSessions.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex flex-col gap-1", children: sortedSessions.map((session) => {
                      const selected = session.id === currentSessionId;
                      return /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: cn(
                        "group flex h-11 w-full items-center rounded-lg border border-solid transition-colors",
                        selected ? "border-primary/25 bg-accent" : "border-transparent hover:bg-accent"
                      ), children: [
                        /* @__PURE__ */ jsxRuntimeExports.jsxs(
                          "button",
                          {
                            type: "button",
                            className: cn(
                              "flex h-full min-w-0 flex-1 items-center justify-between gap-2 border-0 bg-transparent px-3 text-left text-sm",
                              selected ? "text-primary" : "text-muted hover:text-primary"
                            ),
                            onClick: () => onLoadSession(session.id),
                            children: [
                              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "min-w-0 truncate", children: session.name || session.thread_id }),
                              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "shrink-0 text-[11px] text-muted", children: formatSessionDate(session.write_date) })
                            ]
                          }
                        ),
                        confirmArchive === session.id ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
                          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 shrink-0 place-items-center border-0 bg-transparent text-destructive", "aria-label": `确认归档 ${session.name || session.thread_id}`, title: "确认归档", onClick: () => {
                            onArchiveSession(session.id);
                            setConfirmArchive(null);
                          }, children: /* @__PURE__ */ jsxRuntimeExports.jsx(Check, { className: "size-3.5" }) }),
                          /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "mr-1 grid size-7 shrink-0 place-items-center border-0 bg-transparent text-muted", "aria-label": "取消归档", title: "取消归档", onClick: () => setConfirmArchive(null), children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { className: "size-3.5" }) })
                        ] }) : /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "mr-1 grid size-7 shrink-0 place-items-center border-0 bg-transparent text-muted opacity-0 hover:text-destructive group-hover:opacity-100 focus:opacity-100", "aria-label": `归档 ${session.name || session.thread_id}`, title: "归档", onClick: () => setConfirmArchive(session.id), children: /* @__PURE__ */ jsxRuntimeExports.jsx(Archive, { className: "size-3.5" }) })
                      ] }, session.id);
                    }) }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "rounded-lg border border-border bg-accent p-3 text-sm text-muted", children: "暂无会话" }) })
                  ] })
                ]
              }
            )
          ]
        }
      )
    ] });
  }
  function sizeLabel(size) {
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  function WorkspacePanel({ runtime, threadId, references, mentionCount, onToggleReference, onDeleted, onClose }) {
    const [path2, setPath] = reactExports.useState("");
    const [entries, setEntries] = reactExports.useState([]);
    const [loading, setLoading] = reactExports.useState(false);
    const [error, setError] = reactExports.useState("");
    const [preview, setPreview] = reactExports.useState(null);
    const [confirmDelete, setConfirmDelete] = reactExports.useState(null);
    const load = reactExports.useCallback(async () => {
      setLoading(true);
      setError("");
      try {
        setEntries(await runtime.listWorkspace(path2));
      } catch (reason) {
        setEntries([]);
        setError((reason == null ? void 0 : reason.message) || "工作区加载失败。");
      } finally {
        setLoading(false);
      }
    }, [path2, runtime]);
    reactExports.useEffect(() => {
      void load();
    }, [load, threadId]);
    reactExports.useEffect(() => () => {
      if (preview == null ? void 0 : preview.url) URL.revokeObjectURL(preview.url);
    }, [preview]);
    const breadcrumbs = reactExports.useMemo(() => {
      const parts = path2 ? path2.split("/") : [];
      return [{ label: "工作区", path: "" }, ...parts.map((part, index2) => ({
        label: part,
        path: parts.slice(0, index2 + 1).join("/")
      }))];
    }, [path2]);
    const openPreview = async (entry) => {
      setError("");
      try {
        const file = await runtime.readWorkspaceFile(entry.path);
        const url = URL.createObjectURL(file.blob);
        let text2;
        if (file.mimeType.startsWith("text/") || file.mimeType.includes("json")) {
          text2 = await file.blob.text();
        }
        setPreview((current) => {
          if (current == null ? void 0 : current.url) URL.revokeObjectURL(current.url);
          return { entry, url, text: text2 };
        });
      } catch (reason) {
        setError((reason == null ? void 0 : reason.message) || "文件预览失败。");
      }
    };
    const remove = async (entry) => {
      setError("");
      try {
        await runtime.deleteWorkspaceEntry(entry.path, entry.isDirectory);
        onDeleted(entry);
        setConfirmDelete(null);
        if ((preview == null ? void 0 : preview.entry.path) === entry.path) setPreview(null);
        await load();
      } catch (reason) {
        setError((reason == null ? void 0 : reason.message) || "删除失败。");
      }
    };
    return /* @__PURE__ */ jsxRuntimeExports.jsx(
      AsidePanel,
      {
        ariaLabel: "聊天工作区",
        eyebrow: "当前对话",
        title: "工作区",
        icon: /* @__PURE__ */ jsxRuntimeExports.jsx(Folder, { size: 14 }),
        closeLabel: "关闭工作区",
        onClose,
        actions: /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", "aria-label": "刷新工作区", title: "刷新工作区", disabled: loading, onClick: () => void load(), children: /* @__PURE__ */ jsxRuntimeExports.jsx(RefreshCw, { size: 15, className: cn(loading && "animate-spin") }) }),
        className: "agui-workspace-aside",
        children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex h-full min-h-0 flex-col", children: [
          /* @__PURE__ */ jsxRuntimeExports.jsx("nav", { className: "flex min-h-10 flex-wrap items-center gap-1 border-b border-border px-3 py-2", "aria-label": "工作区路径", children: breadcrumbs.map((item, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "inline-flex min-w-0 items-center gap-1", children: [
            index2 ? /* @__PURE__ */ jsxRuntimeExports.jsx(ChevronRight, { size: 12, className: "text-muted" }) : null,
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "max-w-36 truncate border-0 bg-transparent p-0 text-xs text-secondary hover:text-primary", title: item.label, onClick: () => {
              setPath(item.path);
              setPreview(null);
            }, children: item.label })
          ] }, item.path || "root")) }),
          error ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { role: "alert", className: "border-b border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive", children: error }) : null,
          preview ? /* @__PURE__ */ jsxRuntimeExports.jsxs("section", { className: "flex min-h-0 flex-1 flex-col", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("header", { className: "flex h-10 shrink-0 items-center gap-2 border-b border-border px-3", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx(File, { size: 14, className: "text-muted" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("strong", { className: "min-w-0 flex-1 truncate text-xs", title: preview.entry.name, children: preview.entry.name }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-accent hover:text-primary", "aria-label": "关闭预览", onClick: () => setPreview(null), children: /* @__PURE__ */ jsxRuntimeExports.jsx(X, { size: 14 }) })
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "min-h-0 flex-1 overflow-auto bg-background p-3", children: preview.text !== void 0 ? /* @__PURE__ */ jsxRuntimeExports.jsx("pre", { className: "m-0 whitespace-pre-wrap break-words text-xs leading-5 text-secondary", children: preview.text }) : preview.entry.mimeType && preview.entry.mimeType.startsWith("image/") ? /* @__PURE__ */ jsxRuntimeExports.jsx("img", { src: preview.url, alt: preview.entry.name, className: "mx-auto block max-h-full max-w-full object-contain" }) : preview.entry.mimeType === "application/pdf" ? /* @__PURE__ */ jsxRuntimeExports.jsx("iframe", { src: preview.url, title: preview.entry.name, className: "h-full min-h-96 w-full border-0" }) : /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "grid h-full place-items-center text-xs text-muted", children: "此文件可下载，但不支持内嵌预览。" }) })
          ] }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "min-h-0 flex-1 overflow-y-auto", children: [
            loading ? Array.from({ length: 5 }).map((_, index2) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex h-12 animate-pulse items-center gap-3 border-b border-border/60 px-3", children: [
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "size-6 bg-background-secondary" }),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "h-3 flex-1 bg-background-secondary" })
            ] }, index2)) : null,
            !loading && entries.map((entry) => /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex min-h-12 items-center gap-2 border-b border-border/60 px-3 py-1.5 hover:bg-background-secondary/60", children: [
              (() => {
                const selected = references.some((item) => item.path === entry.path);
                const disabled = !selected && references.length + mentionCount >= 5;
                return /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-accent hover:text-primary disabled:opacity-40", disabled, "aria-label": `${selected ? "移除" : "加入"}对话 ${entry.name}`, title: disabled ? "Odoo 引用与工作区引用合计最多 5 个" : "加入对话", onClick: () => onToggleReference(entry), children: selected ? /* @__PURE__ */ jsxRuntimeExports.jsx(Check, { size: 14 }) : /* @__PURE__ */ jsxRuntimeExports.jsx(MessageSquarePlus, { size: 14 }) });
              })(),
              /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "grid size-7 shrink-0 place-items-center text-muted", children: entry.isDirectory ? /* @__PURE__ */ jsxRuntimeExports.jsx(Folder, { size: 16 }) : /* @__PURE__ */ jsxRuntimeExports.jsx(File, { size: 15 }) }),
              /* @__PURE__ */ jsxRuntimeExports.jsxs("button", { type: "button", className: "min-w-0 flex-1 border-0 bg-transparent p-0 text-left", onClick: () => entry.isDirectory ? setPath(entry.path) : void openPreview(entry), children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block truncate text-xs text-primary", title: entry.name, children: entry.name }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("span", { className: "block text-[10px] text-muted", children: entry.isDirectory ? "目录" : `${sizeLabel(entry.size)} · 已同步` })
              ] }),
              !entry.isDirectory ? /* @__PURE__ */ jsxRuntimeExports.jsxs(jsxRuntimeExports.Fragment, { children: [
                /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-accent hover:text-primary", "aria-label": `预览 ${entry.name}`, title: "预览", onClick: () => void openPreview(entry), children: /* @__PURE__ */ jsxRuntimeExports.jsx(Eye, { size: 14 }) }),
                /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-accent hover:text-primary", "aria-label": `下载 ${entry.name}`, title: "下载", onClick: () => void runtime.downloadWorkspaceFile(entry.path).catch((reason) => setError(reason.message)), children: /* @__PURE__ */ jsxRuntimeExports.jsx(Download, { size: 14 }) })
              ] }) : null,
              /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "grid size-7 place-items-center border-0 bg-transparent text-muted hover:bg-destructive/10 hover:text-destructive", "aria-label": `删除 ${entry.name}`, title: "删除", onClick: () => setConfirmDelete(entry), children: /* @__PURE__ */ jsxRuntimeExports.jsx(Trash2, { size: 14 }) })
            ] }, entry.path)),
            !loading && !entries.length ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "grid h-40 place-items-center text-xs text-muted", children: "工作区为空" }) : null
          ] }),
          confirmDelete ? /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex min-h-12 items-center gap-2 border-t border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning", children: [
            /* @__PURE__ */ jsxRuntimeExports.jsxs("span", { className: "min-w-0 flex-1 truncate", title: confirmDelete.name, children: [
              "删除“",
              confirmDelete.name,
              "”？"
            ] }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "h-7 border border-warning/40 bg-background-panel px-2", onClick: () => void remove(confirmDelete), children: "确认" }),
            /* @__PURE__ */ jsxRuntimeExports.jsx("button", { type: "button", className: "h-7 border border-border bg-background-panel px-2", onClick: () => setConfirmDelete(null), children: "取消" })
          ] }) : null
        ] })
      }
    );
  }
  function DefaultErrorMessage({ error }) {
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "mx-auto mb-2 w-full max-w-3xl px-4 text-sm text-destructive", children: error });
  }
  function AguiChatApp({ runtime, props }) {
    var _a, _b;
    const [snapshot, setSnapshot] = reactExports.useState(() => runtime.getSnapshot());
    const [previewAttachment, setPreviewAttachment] = reactExports.useState(null);
    const [workspaceOpen, setWorkspaceOpen] = reactExports.useState(false);
    const [workspaceReferences, setWorkspaceReferences] = reactExports.useState([]);
    const [composerMentionCount, setComposerMentionCount] = reactExports.useState(0);
    const scrollRef = reactExports.useRef(null);
    const followsStream = reactExports.useRef(true);
    const previousThread = reactExports.useRef(snapshot.threadId);
    const previousUserCount = reactExports.useRef(0);
    const labels = mergeLabels(props.labels);
    const icons = mergeIcons(props.icons);
    const scrollVersion = snapshot.messages.map(
      (message) => {
        var _a2;
        return `${message.id}:${String(message.content || "").length}:${((_a2 = message.tool_calls) == null ? void 0 : _a2.length) || 0}`;
      }
    ).join("|");
    reactExports.useEffect(() => runtime.subscribe(() => setSnapshot(runtime.getSnapshot())), [runtime]);
    reactExports.useEffect(() => {
      setWorkspaceReferences([]);
      setComposerMentionCount(0);
      setPreviewAttachment(null);
      setWorkspaceOpen(false);
    }, [snapshot.threadId]);
    reactExports.useEffect(() => {
      const element2 = scrollRef.current;
      if (!element2) return;
      const observer = new MutationObserver(() => {
        if (followsStream.current) element2.scrollTop = element2.scrollHeight;
      });
      observer.observe(element2, { childList: true, characterData: true, subtree: true });
      return () => observer.disconnect();
    }, []);
    reactExports.useEffect(() => {
      const element2 = scrollRef.current;
      if (!element2) return;
      const userCount = snapshot.messages.filter((message) => message.role === "user").length;
      const threadChanged = previousThread.current !== snapshot.threadId;
      const userAdded = userCount > previousUserCount.current;
      if (threadChanged || userAdded || followsStream.current) {
        element2.scrollTop = element2.scrollHeight;
        followsStream.current = true;
      }
      previousThread.current = snapshot.threadId;
      previousUserCount.current = userCount;
    }, [snapshot.threadId, scrollVersion]);
    const handleSend = function(content2, attachments, selection, skills, references) {
      return runtime.send(content2, attachments, selection, void 0, skills, references).then(function(sent) {
        if (!sent) return false;
        setWorkspaceReferences([]);
        const mentions = Array.isArray(selection) ? selection : void 0;
        const menuMention = selection && !Array.isArray(selection) ? selection : void 0;
        observeInteraction(function() {
          var _a2;
          (_a2 = props.onInteraction) == null ? void 0 : _a2.call(props, {
            type: "send",
            content: content2,
            attachments,
            mentions,
            menuMention,
            skills,
            workspaceReferences: references
          });
        });
        return true;
      });
    };
    return /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "agui-chat-react relative", children: /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "flex h-full min-h-0 overflow-hidden bg-background/90 text-secondary", children: [
      /* @__PURE__ */ jsxRuntimeExports.jsx(
        Sidebar,
        {
          snapshot,
          initialCollapsed: (_a = props.ui) == null ? void 0 : _a.initialSidebarCollapsed,
          onNewSession: () => void runtime.newSession(),
          onRefreshSessions: () => void runtime.refreshSessions(),
          onLoadSession: (sessionId) => void runtime.loadSession(sessionId),
          onArchiveSession: (sessionId) => void runtime.archiveSession(sessionId),
          labels
        }
      ),
      /* @__PURE__ */ jsxRuntimeExports.jsxs("main", { className: "relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background-panel", children: [
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          "div",
          {
            ref: scrollRef,
            className: "min-h-0 flex-1 overflow-y-auto",
            onScroll: (event) => {
              const element2 = event.currentTarget;
              followsStream.current = element2.scrollHeight - element2.scrollTop - element2.clientHeight <= 24;
            },
            children: /* @__PURE__ */ jsxRuntimeExports.jsx(
              Messages,
              {
                messages: snapshot.messages,
                running: snapshot.running,
                suggestions: props.suggestions,
                toolRenderers: props.toolRenderers,
                labels,
                icons,
                components: props.components,
                hostState: snapshot.hostState,
                onSelectRelation: (tool, candidates) => {
                  void runtime.selectRelationCandidates(tool, candidates).then((content2) => {
                    if (content2) observeInteraction(() => {
                      var _a2;
                      return (_a2 = props.onInteraction) == null ? void 0 : _a2.call(props, { type: "send", content: content2, attachments: [] });
                    });
                  });
                },
                onSelectRecord: (tool, candidate) => {
                  void runtime.selectRecordCandidate(tool, candidate).then((content2) => {
                    if (content2) observeInteraction(() => {
                      var _a2;
                      return (_a2 = props.onInteraction) == null ? void 0 : _a2.call(props, {
                        type: "send",
                        content: content2,
                        attachments: [],
                        recordSelection: {
                          ...candidate,
                          snapshotId: snapshot.hostState.snapshotId,
                          hostRevision: snapshot.hostState.hostRevision
                        }
                      });
                    });
                  });
                },
                onRemoveMenuMention: (messageId) => runtime.removeMenuMention(messageId),
                onRemoveMention: (messageId, referenceId) => runtime.removeMention(messageId, referenceId),
                onCopy: (message) => {
                  var _a2;
                  const write = (_a2 = navigator.clipboard) == null ? void 0 : _a2.writeText(asText(message.content));
                  if (write) void write.catch(() => void 0);
                  observeInteraction(() => {
                    var _a3;
                    return (_a3 = props.onInteraction) == null ? void 0 : _a3.call(props, { type: "copy", message });
                  });
                },
                onFeedback: (message, feedback) => {
                  observeInteraction(() => {
                    var _a2;
                    return (_a2 = props.onFeedback) == null ? void 0 : _a2.call(props, message, feedback);
                  });
                  observeInteraction(() => {
                    var _a2;
                    return (_a2 = props.onInteraction) == null ? void 0 : _a2.call(props, { type: "feedback", message, feedback });
                  });
                },
                onPreviewAttachment: (attachment) => {
                  setWorkspaceOpen(false);
                  setPreviewAttachment(attachment);
                },
                onRegenerate: (messageId) => {
                  const message = snapshot.messages.find((candidate) => candidate.id === messageId);
                  void runtime.regenerate(messageId);
                  if (message) observeInteraction(() => {
                    var _a2;
                    return (_a2 = props.onInteraction) == null ? void 0 : _a2.call(props, { type: "regenerate", message });
                  });
                },
                onSuggestion: (suggestion) => {
                  void runtime.send(suggestion.message);
                  observeInteraction(() => {
                    var _a2;
                    return (_a2 = props.onInteraction) == null ? void 0 : _a2.call(props, { type: "suggestion", suggestion });
                  });
                  observeInteraction(() => {
                    var _a2;
                    return (_a2 = props.onInteraction) == null ? void 0 : _a2.call(props, { type: "send", content: suggestion.message, attachments: [] });
                  });
                },
                onConfirmTool: (tool, approved) => void runtime.confirmTool(tool, approved),
                onUndoTool: (tool) => void runtime.undoTool(tool)
              }
            )
          }
        ),
        snapshot.error ? React.createElement(((_b = props.components) == null ? void 0 : _b.ErrorMessage) || DefaultErrorMessage, { error: snapshot.error }) : null,
        /* @__PURE__ */ jsxRuntimeExports.jsx(
          ChatInput,
          {
            running: snapshot.running,
            disabled: snapshot.loadingSessions,
            attachments: props.attachments,
            menuOptions: props.menuOptions || [],
            agentSkills: props.agentSkills || [],
            hostBridge: props.hostBridge,
            workspaceReferences,
            onRemoveWorkspaceReference: (id) => setWorkspaceReferences((current) => current.filter((item) => item.id !== id)),
            onMentionsChange: setComposerMentionCount,
            labels,
            icons,
            onSend: handleSend,
            onStop: () => {
              runtime.stop();
              observeInteraction(() => {
                var _a2;
                return (_a2 = props.onInteraction) == null ? void 0 : _a2.call(props, { type: "stop" });
              });
            },
            onUpload: (file, onProgress) => runtime.uploadAttachment(file, onProgress),
            onRemove: (attachmentId) => runtime.deleteAttachment(attachmentId),
            onOpenWorkspace: () => {
              setPreviewAttachment(null);
              setWorkspaceOpen(true);
            }
          },
          snapshot.threadId
        )
      ] }),
      previewAttachment ? /* @__PURE__ */ jsxRuntimeExports.jsx(
        FilePreviewPanel,
        {
          attachment: previewAttachment,
          labels,
          onClose: () => setPreviewAttachment(null)
        }
      ) : null,
      workspaceOpen ? /* @__PURE__ */ jsxRuntimeExports.jsx(
        WorkspacePanel,
        {
          runtime,
          threadId: snapshot.threadId,
          references: workspaceReferences,
          mentionCount: composerMentionCount,
          onToggleReference: (entry) => setWorkspaceReferences((current) => {
            const selected = current.some((item) => item.path === entry.path);
            if (selected) return current.filter((item) => item.path !== entry.path);
            if (current.length + composerMentionCount >= 5) return current;
            return [...current, { id: `workspace:${entry.path}`, path: entry.path, name: entry.name, isDirectory: entry.isDirectory }];
          }),
          onDeleted: (entry) => setWorkspaceReferences((current) => current.filter((item) => item.path !== entry.path && !(entry.isDirectory && item.path.startsWith(`${entry.path}/`)))),
          onClose: () => setWorkspaceOpen(false)
        }
      ) : null
    ] }) });
  }
  const AGUI_ODOO_PROTOCOL = "agui.odoo.v2";
  function pathSegments(path2) {
    return String(path2 || "").split("/").slice(1).map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"));
  }
  function containerFor(document2, path2) {
    let target = document2;
    for (let index2 = 0; index2 < path2.length - 1; index2 += 1) {
      const segment = path2[index2];
      if (target[segment] === void 0 || target[segment] === null) {
        target[segment] = /^\d+$/.test(path2[index2 + 1]) ? [] : {};
      }
      target = target[segment];
    }
    return { target, key: path2[path2.length - 1] };
  }
  function applyJsonPatch(document2, patch2) {
    if (!Array.isArray(patch2)) {
      return document2;
    }
    const next = clone(document2);
    patch2.forEach((operation) => {
      if (!operation || typeof operation !== "object") {
        return;
      }
      const item = operation;
      const path2 = pathSegments(item.path || "");
      if (!path2.length) {
        return;
      }
      const { target, key } = containerFor(next, path2);
      if (item.op === "remove") {
        if (Array.isArray(target)) {
          target.splice(key === "-" ? target.length - 1 : Number(key), 1);
        } else {
          delete target[key];
        }
      } else if (item.op === "add" || item.op === "replace") {
        if (Array.isArray(target)) {
          if (key === "-") {
            target.push(item.value);
          } else {
            target[Number(key)] = item.value;
          }
        } else {
          target[key] = item.value;
        }
      }
    });
    return next;
  }
  function deepMerge(target, source) {
    if (!source || typeof source !== "object" || Array.isArray(source)) {
      return target;
    }
    const next = { ...target };
    Object.entries(source).forEach(([key, value]) => {
      if (value && typeof value === "object" && !Array.isArray(value) && next[key] && typeof next[key] === "object" && !Array.isArray(next[key])) {
        next[key] = deepMerge(next[key], value);
      } else {
        next[key] = value;
      }
    });
    return next;
  }
  function endpoint(props) {
    const value = String(props.runtimeUrl || "").trim();
    if (!value) {
      throw new Error("尚未配置 AG-UI 运行服务。");
    }
    if (value.startsWith("/") && !value.startsWith("//") && !value.includes("://")) {
      return value;
    }
    if (props.allowCrossOriginDev && /^https?:\/\//i.test(value)) {
      return value;
    }
    throw new Error("不允许使用此 AG-UI 运行服务地址。");
  }
  function transportError(status) {
    const messages = {
      401: "登录状态已过期，请重新登录。",
      403: "您没有运行此智能体的权限。",
      429: "请求过于频繁，请稍后重试。"
    };
    return new Error(messages[status] || `AG-UI 请求失败（HTTP ${status}）。`);
  }
  function validateHandshake(props) {
    const handshake = props.handshake;
    if (!handshake || handshake.protocol !== AGUI_ODOO_PROTOCOL) {
      throw new Error("Odoo AG-UI 协议握手失败。");
    }
    if (handshake.agentProtocol !== AGUI_ODOO_PROTOCOL) {
      throw new Error("AgentOS AG-UI 协议握手失败。");
    }
    if (!handshake.moduleVersion || handshake.moduleVersion !== handshake.bundleVersion || handshake.bundleVersion !== handshake.agentBundleVersion) {
      throw new Error("AG-UI 模块、前端资源与 AgentOS 版本不匹配。");
    }
    if (!/^[a-f0-9]{64}$/.test(handshake.commandCatalogHash || "") || handshake.commandCatalogHash !== handshake.agentCommandCatalogHash) {
      throw new Error("AG-UI 命令目录不匹配。");
    }
    if (!props.hostState || props.hostState.protocol !== AGUI_ODOO_PROTOCOL) {
      throw new Error("Odoo 宿主快照协议与运行服务不匹配。");
    }
  }
  function normalizeToolCalls(toolCalls) {
    return (toolCalls || []).map((rawTool) => {
      const tool = rawTool;
      const id = toolCallId(tool);
      const fn = tool.function || {};
      const name2 = fn.name || toolName(tool);
      const args = fn.arguments ?? toolArgs(tool);
      if (!id || !name2) return null;
      return {
        id,
        type: tool.type || "function",
        function: {
          name: String(name2),
          arguments: typeof args === "string" ? args : JSON.stringify(args || {})
        }
      };
    }).filter(Boolean);
  }
  function transportMessage(message) {
    var _a;
    const role = message.role === "agent" ? "assistant" : message.role;
    if (role === "assistant") {
      const transported = { id: message.id, role: "assistant" };
      if (message.content) transported.content = asText(message.content);
      const toolCalls = normalizeToolCalls(
        message.toolCalls && message.toolCalls.length ? message.toolCalls : message.tool_calls
      );
      if (toolCalls.length) transported.toolCalls = toolCalls;
      return transported;
    }
    if (role === "tool") {
      return {
        id: message.id,
        role: "tool",
        content: asText(message.content),
        toolCallId: String(message.toolCallId || message.tool_call_id || "")
      };
    }
    if (role === "reasoning" || role === "system" || role === "developer") {
      return { id: message.id, role, content: asText(message.content) };
    }
    return {
      id: message.id,
      role: "user",
      content: typeof message.content === "string" || Array.isArray(message.content) ? message.content : asText(message.content),
      ...((_a = message.attachments) == null ? void 0 : _a.length) ? { attachments: clone(message.attachments) } : {}
    };
  }
  function contextValue(value) {
    return typeof value === "string" ? value : JSON.stringify(value);
  }
  function agentHostContext(host) {
    const action = host.action && typeof host.action === "object" ? host.action : null;
    const record = host.record && typeof host.record === "object" ? host.record : null;
    const selection = host.selection && typeof host.selection === "object" ? host.selection : null;
    return {
      protocol: host.protocol,
      snapshotId: host.snapshotId,
      hostRevision: host.hostRevision,
      interactive: host.interactive,
      surface: host.surface,
      pageTarget: {
        snapshotId: host.snapshotId,
        hostRevision: host.hostRevision
      },
      viewTarget: {
        snapshotId: host.snapshotId,
        hostRevision: host.hostRevision,
        controllerId: host.controller.controllerId,
        dataPointId: host.controller.dataPointId,
        model: (record == null ? void 0 : record.model) || (selection == null ? void 0 : selection.model) || false,
        resId: (record == null ? void 0 : record.resId) || false
      },
      controller: clone(host.controller),
      action: action ? {
        id: action.id,
        xmlId: action.xmlId,
        name: action.name,
        type: action.type,
        resModel: action.resModel,
        resId: action.resId,
        viewMode: action.viewMode,
        domain: action.domain,
        context: action.context,
        target: action.target
      } : false,
      menu: clone(host.menu),
      record: clone(host.record),
      selection: clone(host.selection),
      fields: clone(host.fields),
      capabilities: clone(host.capabilities)
    };
  }
  function normalizeRunContext(props, messages) {
    var _a;
    const context = [{
      description: "Odoo 宿主快照",
      value: contextValue(agentHostContext(props.hostState))
    }];
    if (Array.isArray(props.context)) {
      props.context.forEach((item, index2) => {
        if (item && typeof item === "object" && typeof item.description === "string" && typeof item.value === "string") {
          context.push(clone(item));
        } else {
          context.push({ description: `上下文 ${index2 + 1}`, value: contextValue(item) });
        }
      });
    } else if (props.context && typeof props.context === "object") {
      Object.entries(props.context).forEach(([description, value]) => {
        context.push({ description, value: contextValue(value) });
      });
    }
    if (props.user !== void 0) {
      context.push({ description: "Odoo 用户", value: contextValue(props.user) });
    }
    if (props.agentId !== void 0) {
      context.push({ description: "智能体 ID", value: props.agentId });
    }
    const latestUserMessage = [...messages].reverse().find((message) => message.role === "user");
    const selectedSkills = ((latestUserMessage == null ? void 0 : latestUserMessage.skills) || []).filter((skill) => skill.valid);
    if (selectedSkills.length) {
      context.push({
        description: "已选智能体技能",
        value: contextValue(selectedSkills.map((skill) => ({
          id: skill.id,
          name: skill.name,
          description: skill.description
        })))
      });
    }
    const workspaceReferences = (latestUserMessage == null ? void 0 : latestUserMessage.workspaceReferences) || [];
    if (workspaceReferences.length) {
      context.push({
        description: "已选工作区引用",
        value: contextValue(workspaceReferences.map((reference) => ({
          path: reference.path,
          type: reference.isDirectory ? "directory" : "file",
          tool: reference.isDirectory ? "workspace_list_files" : "workspace_read_file"
        })))
      });
    }
    const mentions = ((latestUserMessage == null ? void 0 : latestUserMessage.mentions) || []).filter((mention) => mention.valid);
    if (mentions.length) {
      context.push({
        description: "已选 Odoo 引用",
        value: contextValue(mentions.map((mention) => ({
          kind: mention.kind,
          action: mention.action,
          token: mention.token,
          label: mention.label,
          detail: mention.detail,
          model: mention.model,
          expiresAt: mention.expiresAt
        })))
      });
    }
    if ((_a = latestUserMessage == null ? void 0 : latestUserMessage.menuMention) == null ? void 0 : _a.valid) {
      const mention = latestUserMessage.menuMention;
      context.push({
        description: "已选 Odoo 菜单",
        value: contextValue({
          menuId: mention.menuId,
          actionId: mention.actionId,
          name: mention.name,
          path: mention.path,
          fullPath: mention.fullPath
        })
      });
    }
    if ((latestUserMessage == null ? void 0 : latestUserMessage.recordSelection) && latestUserMessage.recordSelection.snapshotId === props.hostState.snapshotId && latestUserMessage.recordSelection.hostRevision === props.hostState.hostRevision) {
      context.push({
        description: "已选 Odoo 记录候选项",
        value: contextValue(latestUserMessage.recordSelection)
      });
    }
    return context;
  }
  function buildRunInput(messages, props, threadId, pendingAssistantId, agentState) {
    const runId = uuid();
    return {
      threadId,
      runId,
      requestId: uuid(),
      messages: messages.filter((message) => {
        const isPendingEmpty = message.id === pendingAssistantId && !message.content && !message.streaming_error && !(message.tool_calls && message.tool_calls.length);
        return !isPendingEmpty;
      }).map(transportMessage),
      tools: clone(props.tools || []),
      context: normalizeRunContext(props, messages),
      forwardedProps: {},
      state: {
        protocol: AGUI_ODOO_PROTOCOL,
        host: clone(props.hostState),
        agent: clone(agentState || {})
      },
      resume: clone(props.resume || []),
      agentId: props.agentId
    };
  }
  function validateRunInput(input, props) {
    var _a, _b;
    validateHandshake(props);
    const maxMessages = ((_a = props.limits) == null ? void 0 : _a.messages) ?? 200;
    const maxBytes = ((_b = props.limits) == null ? void 0 : _b.requestBytes) ?? 2 * 1024 * 1024;
    if (input.messages.length > maxMessages) {
      throw new Error(`消息数量超过限制（${maxMessages}）。`);
    }
    if (new TextEncoder().encode(JSON.stringify(input)).byteLength > maxBytes) {
      throw new Error("请求大小超过配置限制。");
    }
  }
  function toolCallFromTransport(toolCall, messageId) {
    if (!toolCall || typeof toolCall !== "object") return null;
    const raw = toolCall;
    const fn = raw.function && typeof raw.function === "object" ? raw.function : {};
    const id = raw.id || raw.tool_call_id || raw.toolCallId;
    const name2 = fn.name || raw.name || raw.tool_name || raw.tool;
    const args = fn.arguments || raw.arguments || raw.tool_args || raw.args;
    if (!id || !name2) return null;
    return {
      id: String(id),
      tool_call_id: String(id),
      name: String(name2),
      tool_name: String(name2),
      tool: String(name2),
      args: parseJson(args),
      tool_args: parseJson(args),
      argsText: typeof args === "string" ? args : JSON.stringify(args || {}),
      status: "pending",
      message_id: messageId
    };
  }
  function eventText(event) {
    return String(event.delta || event.content || event.text || "");
  }
  function eventData(event) {
    return event.data && typeof event.data === "object" ? event.data : event;
  }
  function eventType(event) {
    return String(event.type || event.event || "");
  }
  function isRecord(value) {
    return Boolean(value && typeof value === "object" && !Array.isArray(value));
  }
  function isStateEnvelope(value) {
    return isRecord(value) && value.protocol === AGUI_ODOO_PROTOCOL && isRecord(value.host) && isRecord(value.agent);
  }
  function isLegacySnapshotWrapper(value) {
    const allowedKeys = /* @__PURE__ */ new Set(["snapshot", "type", "timestamp", "rawEvent"]);
    return Object.keys(value).every((key) => allowedKeys.has(key)) && isStateEnvelope(value.snapshot);
  }
  function needsAgentStateCleanup(value) {
    return isStateEnvelope(value) || isRecord(value) && isLegacySnapshotWrapper(value);
  }
  function normalizeAgentState(value) {
    let current = value;
    while (isRecord(current)) {
      if (isStateEnvelope(current)) {
        current = current.agent;
      } else if (isLegacySnapshotWrapper(current)) {
        current = current.snapshot.agent;
      } else {
        break;
      }
    }
    return isRecord(current) ? clone(current) : {};
  }
  function eventToolCallId(event) {
    return String(event.toolCallId || event.tool_call_id || event.id || "");
  }
  function eventToolCallName(event) {
    return String(event.toolCallName || event.tool_call_name || event.name || event.tool || "");
  }
  function normalizeReasoningSteps(value, fallbackContent) {
    const source = Array.isArray(value) && value.length ? value : fallbackContent ? [fallbackContent] : [];
    return source.map((step) => {
      if (typeof step === "string") {
        return {
          title: textSummary(step, 80) || "推理过程",
          content: step
        };
      }
      const raw = step && typeof step === "object" ? step : {};
      const content2 = raw.content || raw.reasoning || raw.text || raw.action || "";
      return {
        title: String(raw.title || textSummary(content2 || raw, 80) || "推理过程"),
        content: typeof content2 === "string" ? content2 : textSummary(content2, 240),
        action: raw.action ? String(raw.action) : void 0,
        result: raw.result ? String(raw.result) : void 0,
        reasoning: raw.reasoning ? String(raw.reasoning) : void 0
      };
    });
  }
  function sessionListFromResult(result) {
    if (Array.isArray(result)) {
      return result;
    }
    if (result && typeof result === "object" && Array.isArray(result.sessions)) {
      return result.sessions;
    }
    return [];
  }
  function sessionFromResult(result) {
    if (result && typeof result === "object" && result.session) {
      return result.session;
    }
    return result || {};
  }
  function mergeMessagesById(remote, local) {
    const localById = new Map(local.map((message) => [message.id, message]));
    const merged = remote.map((message) => localById.get(message.id) || message);
    const remoteIds = new Set(remote.map((message) => message.id));
    local.forEach((message) => {
      if (!remoteIds.has(message.id)) merged.push(message);
    });
    return merged;
  }
  class ChatRuntime {
    constructor(props) {
      __publicField(this, "props");
      __publicField(this, "listeners", /* @__PURE__ */ new Set());
      __publicField(this, "messages", []);
      __publicField(this, "sessions", []);
      __publicField(this, "session", null);
      __publicField(this, "agentState", {});
      __publicField(this, "threadId");
      __publicField(this, "running", false);
      __publicField(this, "transportState", null);
      __publicField(this, "currentRunId", "");
      __publicField(this, "currentRequestId", "");
      __publicField(this, "activeRunContext", null);
      __publicField(this, "loadingSessions", false);
      __publicField(this, "error", "");
      __publicField(this, "pendingAssistantId", null);
      __publicField(this, "activeTextMessageId", null);
      __publicField(this, "activeToolCallId", null);
      __publicField(this, "toolsByKey", {});
      __publicField(this, "executedHostBridgeTools", {});
      __publicField(this, "confirmingHostBridgeTools", {});
      __publicField(this, "resumedToolResults", {});
      __publicField(this, "undoInFlight", {});
      __publicField(this, "saveTimer", null);
      __publicField(this, "saveQueue", Promise.resolve());
      __publicField(this, "workspaceCapability", null);
      __publicField(this, "serverConfirmationDecisions", {});
      var _a;
      this.props = props;
      const initialSession = ((_a = props.session) == null ? void 0 : _a.protocol) === AGUI_ODOO_PROTOCOL ? props.session : null;
      const storedAgentState = (initialSession == null ? void 0 : initialSession.agentState) || props.agentState || {};
      this.threadId = props.threadId || (initialSession == null ? void 0 : initialSession.thread_id) || uuid();
      this.agentState = normalizeAgentState(storedAgentState);
      this.messages = this.normalizeStoredMessages(props.initialMessages || (initialSession == null ? void 0 : initialSession.messages) || []);
      this.sessions = props.sessions || [];
      this.session = initialSession;
      try {
        endpoint(props);
      } catch (error) {
        this.error = error.message;
      }
      this.initSessions();
      if (initialSession && needsAgentStateCleanup(storedAgentState)) {
        this.scheduleSave();
      }
    }
    subscribe(listener) {
      this.listeners.add(listener);
      return () => this.listeners.delete(listener);
    }
    getSnapshot() {
      return {
        messages: this.messages,
        sessions: this.sessions,
        session: this.session,
        hostState: this.props.hostState,
        agentState: this.agentState,
        threadId: this.threadId,
        running: this.running,
        transportState: this.transportState,
        loadingSessions: this.loadingSessions,
        error: this.error
      };
    }
    update(nextProps = {}) {
      var _a;
      const previousThreadId = this.threadId;
      const previousSessionId = (_a = this.session) == null ? void 0 : _a.id;
      this.props = { ...this.props, ...nextProps };
      if (nextProps.sessions) {
        this.sessions = nextProps.sessions;
      }
      if (nextProps.session && nextProps.session.id !== previousSessionId) {
        this.applyLoadedSession(nextProps.session);
      } else if (nextProps.threadId && nextProps.threadId !== previousThreadId) {
        this.resetThread(nextProps.threadId, nextProps.initialMessages || []);
      }
      const menuMentionsChanged = Boolean(nextProps.menuOptions && this.revalidateMenuMentions());
      const mentionsChanged = this.revalidateMentions();
      const skillsChanged = this.revalidateSkills();
      if (menuMentionsChanged || mentionsChanged || skillsChanged) {
        this.notifyMessages();
        this.scheduleSave();
      }
      this.emit();
    }
    cancel() {
      const context = this.activeRunContext;
      if (context) this.cancelRun(context);
    }
    unmount() {
      this.cancel();
      if (this.saveTimer) {
        clearTimeout(this.saveTimer);
        this.saveTimer = null;
      }
      this.listeners.clear();
    }
    async newSession() {
      var _a, _b;
      this.cancel();
      const bridge = this.props.hostBridge || {};
      if (!bridge.createSession) {
        this.resetThread(uuid(), []);
        this.session = null;
        (_b = (_a = this.props).onSessionChange) == null ? void 0 : _b.call(_a, null);
        this.emit();
        return;
      }
      this.loadingSessions = true;
      this.emit();
      try {
        const result = await bridge.createSession({
          surface: this.props.surface || "dock",
          agent_id: this.props.agentId || false
        });
        const session = sessionFromResult(result);
        this.applyLoadedSession(session);
        this.error = "";
        await this.refreshSessions();
      } catch (reason) {
        this.reportError(reason, "创建会话失败。");
      } finally {
        this.loadingSessions = false;
        this.emit();
      }
    }
    async loadSession(sessionId) {
      this.cancel();
      const bridge = this.props.hostBridge || {};
      if (!bridge.loadSession) {
        return;
      }
      this.loadingSessions = true;
      this.emit();
      try {
        const session = sessionFromResult(await bridge.loadSession(sessionId));
        this.applyLoadedSession(session);
        this.error = "";
      } catch (reason) {
        this.reportError(reason, "加载会话失败。");
      } finally {
        this.loadingSessions = false;
        this.emit();
      }
    }
    async refreshSessions() {
      const bridge = this.props.hostBridge || {};
      if (!bridge.listSessions) {
        return true;
      }
      this.loadingSessions = true;
      this.emit();
      try {
        const result = await bridge.listSessions();
        this.sessions = sessionListFromResult(result);
        this.error = "";
        return true;
      } catch (reason) {
        this.reportError(reason, "刷新会话列表失败。");
        return false;
      } finally {
        this.loadingSessions = false;
        this.emit();
      }
    }
    async archiveSession(sessionId) {
      var _a, _b, _c, _d;
      if (this.running || !((_a = this.props.hostBridge) == null ? void 0 : _a.archiveSession)) return false;
      try {
        const result = await Promise.resolve(this.props.hostBridge.archiveSession(sessionId));
        if (isRecord(result) && result.ok === false) {
          throw new Error(String(result.error || result.code || "归档失败。"));
        }
        if (((_b = this.session) == null ? void 0 : _b.id) === sessionId) await this.newSession();
        await this.refreshSessions();
        return true;
      } catch (reason) {
        const error = reason instanceof Error ? reason : new Error(String(reason));
        this.error = error.message;
        (_d = (_c = this.props).onError) == null ? void 0 : _d.call(_c, error);
        this.emit();
        return false;
      }
    }
    async send(content2, attachments = [], selection, recordSelection, skills = [], workspaceReferences = []) {
      var _a, _b, _c, _d, _e, _f, _g, _h, _i, _j, _k, _l, _m, _n;
      const text2 = content2.trim();
      const mentions = Array.isArray(selection) ? selection.map((item) => clone(item)) : [];
      const workspace = workspaceReferences.map((item) => clone(item));
      const menuMention = selection && !Array.isArray(selection) ? selection : void 0;
      const currentMenu = menuMention ? this.resolveMenuMention(menuMention) : void 0;
      if (menuMention && !currentMenu) {
        const error = new Error("所选菜单已失效或无权访问，请重新选择。");
        this.error = error.message;
        (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, error);
        this.emit();
        return false;
      }
      const mentionError = this.validateMentions(mentions);
      if (mentionError) {
        const error = new Error(mentionError);
        this.error = error.message;
        (_d = (_c = this.props).onError) == null ? void 0 : _d.call(_c, error);
        this.emit();
        return false;
      }
      if (mentions.length + workspace.length > 5) {
        const error = new Error("Odoo 引用与工作区引用合计最多 5 个。");
        this.error = error.message;
        (_f = (_e = this.props).onError) == null ? void 0 : _f.call(_e, error);
        this.emit();
        return false;
      }
      if (recordSelection && !this.isCurrentRecordSelection(recordSelection)) {
        const error = new Error("记录候选已过期，请重新筛选。");
        this.error = error.message;
        (_h = (_g = this.props).onError) == null ? void 0 : _h.call(_g, error);
        this.emit();
        return false;
      }
      const skillError = this.validateSkills(skills);
      if (skillError) {
        const error = new Error(skillError);
        this.error = error.message;
        (_j = (_i = this.props).onError) == null ? void 0 : _j.call(_i, error);
        this.emit();
        return false;
      }
      if (!text2 && !attachments.length && !currentMenu && !mentions.length && !workspace.length && !recordSelection || this.running || this.loadingSessions) {
        return false;
      }
      try {
        endpoint(this.props);
      } catch (error) {
        this.error = error.message;
        (_l = (_k = this.props).onError) == null ? void 0 : _l.call(_k, error);
        this.emit();
        return false;
      }
      if (!await this.ensureSession()) return false;
      const messageId = uuid();
      let syncedAttachments;
      try {
        await this.ensureWorkspaceCapability();
        syncedAttachments = await this.syncAttachments(messageId, attachments);
      } catch (reason) {
        const error = reason instanceof Error ? reason : new Error(String(reason));
        this.error = error.message;
        (_n = (_m = this.props).onError) == null ? void 0 : _n.call(_m, error);
        this.emit();
        return false;
      }
      this.messages.push({
        id: messageId,
        role: "user",
        content: text2,
        attachments: clone(syncedAttachments),
        mentions: mentions.length ? mentions : void 0,
        workspaceReferences: workspace.length ? workspace : void 0,
        skills: skills.length ? skills.map((skill) => ({ ...skill, valid: true })) : void 0,
        menuMention: currentMenu,
        recordSelection: recordSelection ? clone(recordSelection) : void 0,
        created_at: Date.now()
      });
      this.pendingAssistantId = uuid();
      this.messages.push({
        id: this.pendingAssistantId,
        role: "assistant",
        content: "",
        tool_calls: [],
        created_at: Date.now()
      });
      this.executedHostBridgeTools = {};
      this.confirmingHostBridgeTools = {};
      this.resumedToolResults = {};
      this.serverConfirmationDecisions = {};
      this.undoInFlight = {};
      const context = this.createRunContext();
      await this.executeRunLifecycle(context, () => this.run(context, 0));
      if (this.transportState === "error") {
        return false;
      }
      return true;
    }
    stop() {
      this.cancel();
    }
    async confirmTool(tool, approved) {
      const bridge = this.props.hostBridge;
      const key = toolKey(tool);
      const current = this.toolsByKey[key] || tool;
      const result = current.result && typeof current.result === "object" ? current.result : {};
      if (result.server_confirmation === true) {
        await this.confirmServerTool(current, approved);
        return;
      }
      const authorizationId = String(result.authorization_id || tool.confirmation_id || "");
      if (!(bridge == null ? void 0 : bridge.confirmTool) || !authorizationId || this.running || current.status !== "needs_confirmation" || this.confirmingHostBridgeTools[key]) return;
      const call = {
        id: toolCallId(current) || false,
        tool: toolName(current),
        arguments: toolArgs(current),
        message_id: current.message_id || false,
        context: {
          requestId: this.currentRequestId,
          runId: this.currentRunId,
          threadId: this.threadId,
          selectedMentionTokens: this.latestMentionTokens()
        }
      };
      this.confirmingHostBridgeTools[key] = true;
      const context = this.createRunContext();
      await this.executeRunLifecycle(context, async () => {
        const resultPromise = Promise.resolve().then(() => bridge.confirmTool(call, authorizationId, approved)).then(
          (value) => this.normalizeHostBridgeSuccess(current, value),
          (error) => ({
            ok: false,
            operation: toolName(current),
            error: (error == null ? void 0 : error.message) || "工具确认失败。"
          })
        ).then((finalResult2) => {
          if (finalResult2.needs_confirmation) {
            const args = isRecord(toolArgs(current)) ? toolArgs(current) : {};
            const nextArgs = {
              ...args,
              ...finalResult2.target ? { target: finalResult2.target } : {},
              ...finalResult2.patch ? { patch: finalResult2.patch } : {}
            };
            this.mergeTool({
              id: toolCallId(current),
              name: toolName(current),
              args: nextArgs,
              tool_args: nextArgs,
              result: finalResult2,
              status: "needs_confirmation",
              needs_confirmation: true,
              error: false
            });
            this.notifyMessages();
            this.emit();
          } else {
            this.recordHostBridgeResult(current, finalResult2, context);
          }
          return finalResult2;
        });
        const persistedResult = resultPromise.then(async (finalResult2) => {
          await this.persistImmediately();
          return finalResult2;
        });
        const finalResult = await this.awaitWithRunCancellation(context, persistedResult);
        this.throwIfRunCancelled(context);
        if (finalResult.needs_confirmation || this.resumedToolResults[key]) return;
        this.resumedToolResults[key] = true;
        await this.run(context, 0);
      }, () => {
        delete this.confirmingHostBridgeTools[key];
      });
    }
    async confirmServerTool(tool, approved) {
      const key = toolKey(tool);
      if (this.running || this.serverConfirmationDecisions[key] !== void 0 || tool.status !== "needs_confirmation") return;
      this.serverConfirmationDecisions[key] = approved;
      tool.status = "running";
      tool.needs_confirmation = false;
      this.notifyMessages();
      this.emit();
      const paused = Object.values(this.toolsByKey).filter(
        (candidate) => isRecord(candidate.result) && candidate.result.server_confirmation === true
      );
      if (!paused.length || paused.some(
        (candidate) => this.serverConfirmationDecisions[toolKey(candidate)] === void 0
      )) return;
      paused.forEach((candidate) => {
        const accepted = this.serverConfirmationDecisions[toolKey(candidate)];
        const id = toolCallId(candidate);
        const content2 = accepted ? { accepted: true } : { accepted: false, note: "用户拒绝执行此工具。" };
        this.messages.push({
          id: `tool-server-${id || uuid()}`,
          role: "tool",
          name: toolName(candidate),
          toolCallId: id,
          tool_call_id: id,
          content: JSON.stringify(content2),
          hidden: true,
          created_at: Date.now()
        });
        if (!accepted) {
          candidate.status = "error";
          candidate.error = "用户拒绝执行此工具。";
        }
        candidate.result = {
          ...isRecord(candidate.result) ? candidate.result : {},
          server_confirmation: false,
          accepted
        };
      });
      this.pendingAssistantId = uuid();
      this.messages.push({
        id: this.pendingAssistantId,
        role: "assistant",
        content: "",
        tool_calls: [],
        created_at: Date.now()
      });
      const context = this.createRunContext();
      await this.executeRunLifecycle(context, () => this.run(context, 0));
    }
    async undoTool(tool) {
      var _a;
      const current = this.toolsByKey[toolKey(tool)] || tool;
      const result = isRecord(current.result) ? current.result : {};
      const receipt = isRecord(result.receipt) ? result.receipt : {};
      const undo = isRecord(receipt.undo) ? receipt.undo : {};
      const authorizationId = String(undo.authorization_id || "");
      if (!((_a = this.props.hostBridge) == null ? void 0 : _a.undoTool) || !authorizationId || undo.status === "undone" || this.undoInFlight[authorizationId]) return;
      this.undoInFlight[authorizationId] = true;
      receipt.undo = { ...undo, status: "running" };
      this.mergeTool({ ...current, result: { ...result, receipt } });
      this.notifyMessages();
      this.emit();
      try {
        const value = this.normalizeHostBridgeSuccess(
          { name: "odoo.undo_current_form" },
          await this.props.hostBridge.undoTool(authorizationId)
        );
        const succeeded = value.ok === true && value.undone === true;
        receipt.undo = {
          ...undo,
          status: succeeded ? "undone" : "error",
          error: succeeded ? false : value.error || value.code || "undo_failed"
        };
        this.mergeTool({ ...current, result: { ...result, receipt, undoResult: value } });
      } catch (error) {
        receipt.undo = { ...undo, status: "error", error: error.message };
        this.mergeTool({ ...current, result: { ...result, receipt } });
      } finally {
        delete this.undoInFlight[authorizationId];
        this.notifyMessages();
        this.emit();
        await this.persistImmediately();
      }
    }
    async selectRelationCandidates(tool, candidates) {
      var _a, _b;
      if (this.running || toolName(tool) !== "odoo.search_relation" || !candidates.length) return null;
      const result = tool.result && typeof tool.result === "object" ? tool.result : {};
      const currentHost = this.props.hostState;
      if (result.snapshotId !== currentHost.snapshotId || result.hostRevision !== currentHost.hostRevision) {
        const error = new Error("关系候选已过期，请根据当前表单重新查询。");
        this.error = error.message;
        (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, error);
        this.emit();
        return null;
      }
      const available = Array.isArray(result.candidates) ? result.candidates : [];
      const availableIds = new Set(available.map((candidate) => Number(candidate.id)));
      const unique = candidates.filter(
        (candidate, index2, list2) => Number.isInteger(candidate.id) && candidate.id > 0 && availableIds.has(candidate.id) && list2.findIndex((item) => item.id === candidate.id) === index2
      );
      const fieldType = String(result.fieldType || "");
      const operation = String(result.relationOperation || "");
      if (!unique.length || fieldType === "many2one" && unique.length !== 1) return null;
      const incompatible = unique.some(
        (candidate) => operation === "link" ? candidate.selected : operation === "unlink" ? !candidate.selected : false
      );
      if (incompatible) return null;
      const selection = {
        field: String(result.field || ""),
        rowToken: typeof result.rowToken === "string" ? result.rowToken : false,
        operation,
        records: unique.map((candidate) => ({ id: candidate.id, displayName: candidate.displayName })),
        snapshotId: String(result.snapshotId || "")
      };
      const names = unique.map((candidate) => candidate.displayName + " (#" + candidate.id + ")").join("、");
      const content2 = "我选择了" + String(result.fieldLabel || result.field || "关系字段") + "：" + names + "。关系选择数据：" + JSON.stringify(selection);
      await this.send(content2);
      return content2;
    }
    async selectRecordCandidate(tool, candidate) {
      var _a, _b;
      if (this.running || toolName(tool) !== "odoo.apply_filter") return null;
      const result = isRecord(tool.result) ? tool.result : {};
      const host = this.props.hostState;
      if (result.snapshotId !== host.snapshotId || result.hostRevision !== host.hostRevision) {
        const error = new Error("记录候选已过期，请重新筛选。");
        this.error = error.message;
        (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, error);
        this.emit();
        return null;
      }
      const candidates = Array.isArray(result.candidates) ? result.candidates : [];
      if (!candidates.some((item) => item.token === candidate.token)) return null;
      const selection = {
        token: candidate.token,
        displayName: candidate.displayName,
        snapshotId: host.snapshotId,
        hostRevision: host.hostRevision
      };
      if (!this.isCurrentRecordSelection(selection)) return null;
      const content2 = `选择记录：${candidate.displayName}`;
      await this.send(content2, [], void 0, selection);
      return content2;
    }
    removeMenuMention(messageId) {
      if (this.running) return;
      const message = this.messages.find((item) => item.id === messageId && item.role === "user");
      if (!(message == null ? void 0 : message.menuMention)) return;
      delete message.menuMention;
      this.notifyMessages();
      this.scheduleSave();
      this.emit();
    }
    removeMention(messageId, referenceId) {
      var _a;
      if (this.running) return;
      const message = this.messages.find((item) => item.id === messageId && item.role === "user");
      if (!((_a = message == null ? void 0 : message.mentions) == null ? void 0 : _a.some((mention) => mention.id === referenceId))) return;
      message.mentions = message.mentions.filter((mention) => mention.id !== referenceId);
      if (!message.mentions.length) delete message.mentions;
      this.notifyMessages();
      this.scheduleSave();
      this.emit();
    }
    async regenerate(messageId) {
      var _a, _b, _c, _d, _e, _f, _g, _h;
      if (this.running) {
        return;
      }
      const assistantIndex = this.messages.findIndex(
        (message) => message.id === messageId && (message.role === "assistant" || message.role === "agent")
      );
      if (assistantIndex < 0) {
        return;
      }
      let userIndex = assistantIndex - 1;
      while (userIndex >= 0 && this.messages[userIndex].role !== "user") {
        userIndex -= 1;
      }
      if (userIndex < 0) {
        return;
      }
      const userMessage = this.messages[userIndex];
      const mentionError = this.validateMentions(userMessage.mentions || []);
      if (mentionError) {
        const error = new Error(`消息中的对象引用无效，无法重新执行：${mentionError}`);
        this.error = error.message;
        (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, error);
        this.emit();
        return;
      }
      const skillError = this.validateSkills(userMessage.skills || []);
      if (skillError) {
        const error = new Error(`消息中的技能无效，无法重新执行：${skillError}`);
        this.error = error.message;
        (_d = (_c = this.props).onError) == null ? void 0 : _d.call(_c, error);
        this.emit();
        return;
      }
      if (userMessage.menuMention && !this.resolveMenuMention(userMessage.menuMention)) {
        const error = new Error("消息中的菜单已失效，无法重新执行。");
        this.error = error.message;
        (_f = (_e = this.props).onError) == null ? void 0 : _f.call(_e, error);
        this.emit();
        return;
      }
      if (userMessage.recordSelection && !this.isCurrentRecordSelection(userMessage.recordSelection)) {
        const error = new Error("消息中的记录候选已过期，请重新筛选。");
        this.error = error.message;
        (_h = (_g = this.props).onError) == null ? void 0 : _h.call(_g, error);
        this.emit();
        return;
      }
      this.messages = this.messages.slice(0, userIndex + 1);
      this.pendingAssistantId = uuid();
      this.messages.push({
        id: this.pendingAssistantId,
        role: "assistant",
        content: "",
        tool_calls: [],
        created_at: Date.now()
      });
      this.executedHostBridgeTools = {};
      this.confirmingHostBridgeTools = {};
      this.resumedToolResults = {};
      this.undoInFlight = {};
      const context = this.createRunContext();
      await this.executeRunLifecycle(context, () => this.run(context, 0));
    }
    async uploadAttachment(file, onProgress) {
      await this.ensureSession();
      if (!this.session) {
        throw new Error("上传附件前需要先创建聊天会话。");
      }
      const sessionId = String(this.session.id || "");
      if (!/^\d+$/.test(sessionId)) {
        throw new Error("当前聊天会话不可用。");
      }
      return new Promise((resolve, reject) => {
        const form = new FormData();
        form.append("chat_session_id", sessionId);
        form.append("file", file);
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/agui_chat/attachment/upload");
        xhr.withCredentials = true;
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            onProgress == null ? void 0 : onProgress(Math.round(event.loaded / event.total * 100));
          }
        };
        xhr.onerror = () => reject(new Error("附件上传失败。"));
        xhr.onload = () => {
          let payload = {};
          try {
            payload = JSON.parse(xhr.responseText || "{}");
          } catch (_error) {
            reject(new Error("附件上传响应无效。"));
            return;
          }
          if (xhr.status < 200 || xhr.status >= 300 || !payload.attachment) {
            reject(new Error(payload.error || "附件上传失败。"));
            return;
          }
          onProgress == null ? void 0 : onProgress(100);
          resolve(payload.attachment);
        };
        xhr.send(form);
      });
    }
    async deleteAttachment(attachmentId) {
      const response = await fetch("/agui_chat/attachment/delete", {
        method: "POST",
        credentials: this.props.credentials || "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ attachment_id: attachmentId })
      });
      if (!response.ok) {
        throw new Error("附件删除失败。");
      }
    }
    async listWorkspace(path2 = "") {
      const capability = await this.ensureWorkspaceCapability(true);
      if (!capability) throw new Error("工作区 capability 不可用。");
      const query = new URLSearchParams({ threadId: this.threadId, path: path2 });
      const response = await fetch(`${this.workspaceEndpoint("/workspace/files")}?${query}`, {
        credentials: this.runtimeCredentials(),
        headers: this.workspaceHeaders(capability)
      });
      const payload = await this.workspaceJson(response);
      return Array.isArray(payload.entries) ? payload.entries : [];
    }
    async readWorkspaceFile(path2) {
      const capability = await this.ensureWorkspaceCapability(true);
      if (!capability) throw new Error("工作区 capability 不可用。");
      const query = new URLSearchParams({ threadId: this.threadId, path: path2 });
      const response = await fetch(`${this.workspaceEndpoint("/workspace/file")}?${query}`, {
        credentials: this.runtimeCredentials(),
        headers: this.workspaceHeaders(capability)
      });
      if (!response.ok) throw new Error(await this.workspaceError(response));
      return {
        blob: await response.blob(),
        mimeType: response.headers.get("content-type") || "application/octet-stream"
      };
    }
    async downloadWorkspaceFile(path2) {
      const capability = await this.ensureWorkspaceCapability(true);
      if (!capability) throw new Error("工作区 capability 不可用。");
      const query = new URLSearchParams({ threadId: this.threadId, path: path2, download: "true" });
      const response = await fetch(`${this.workspaceEndpoint("/workspace/file")}?${query}`, {
        credentials: this.runtimeCredentials(),
        headers: this.workspaceHeaders(capability)
      });
      if (!response.ok) throw new Error(await this.workspaceError(response));
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = path2.split("/").pop() || "download";
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    }
    async deleteWorkspaceEntry(path2, recursive = false) {
      const capability = await this.ensureWorkspaceCapability(true);
      if (!capability) throw new Error("工作区 capability 不可用。");
      const response = await fetch(this.workspaceEndpoint("/workspace/file"), {
        method: "DELETE",
        credentials: this.runtimeCredentials(),
        headers: {
          ...this.workspaceHeaders(capability),
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ threadId: this.threadId, path: path2, recursive })
      });
      if (!response.ok) throw new Error(await this.workspaceError(response));
    }
    runtimeCredentials() {
      return this.props.credentials || (this.props.allowCrossOriginDev ? "include" : "same-origin");
    }
    workspaceEndpoint(path2) {
      const runtime = endpoint(this.props);
      return `${runtime.slice(0, -"/agui".length)}${path2}`;
    }
    workspaceHeaders(capability) {
      return {
        "X-AGUI-Capability": capability.capability,
        "X-AGUI-Thread": this.threadId
      };
    }
    async workspaceError(response) {
      try {
        const payload = await response.clone().json();
        return payload.detail || payload.error || `工作区请求失败（HTTP ${response.status}）。`;
      } catch (_error) {
        return `工作区请求失败（HTTP ${response.status}）。`;
      }
    }
    async workspaceJson(response) {
      if (!response.ok) throw new Error(await this.workspaceError(response));
      return response.json();
    }
    async ensureWorkspaceCapability(required = false) {
      var _a;
      const current = this.workspaceCapability;
      if (current && current.threadId === this.threadId && current.expiresAt > Date.now() / 1e3 + 30) {
        return current;
      }
      const bridge = this.props.hostBridge;
      if (!(bridge == null ? void 0 : bridge.getWorkspaceCapability)) {
        if (required) throw new Error("Odoo 未提供工作区 capability。");
        return null;
      }
      if (!((_a = this.session) == null ? void 0 : _a.id)) throw new Error("当前聊天会话不可用。");
      const result = await Promise.resolve(bridge.getWorkspaceCapability(this.session.id));
      if ((result == null ? void 0 : result.ok) === false || !result.capability || !result.threadId || typeof result.expiresAt !== "number" || result.threadId !== this.threadId) {
        throw new Error((result == null ? void 0 : result.error) || (result == null ? void 0 : result.code) || "工作区 capability 获取失败。");
      }
      this.workspaceCapability = {
        capability: result.capability,
        threadId: result.threadId,
        expiresAt: result.expiresAt
      };
      return this.workspaceCapability;
    }
    safeAttachmentName(name2, index2) {
      const basename2 = name2.replace(/\\/g, "/").split("/").pop() || `attachment-${index2 + 1}`;
      const safe = basename2.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^\.+/, "").slice(0, 120);
      return `${index2 + 1}-${safe || `attachment-${index2 + 1}`}`;
    }
    async syncAttachments(messageId, attachments) {
      var _a;
      if (!attachments.length) return [];
      if (!((_a = this.props.hostBridge) == null ? void 0 : _a.getWorkspaceCapability)) return clone(attachments);
      const capability = await this.ensureWorkspaceCapability(true);
      if (!capability) throw new Error("工作区 capability 不可用。");
      const synced = [];
      try {
        for (let index2 = 0; index2 < attachments.length; index2 += 1) {
          const attachment = attachments[index2];
          const source = await fetch(`/agui_chat/attachment/${encodeURIComponent(attachment.id)}`, {
            credentials: this.props.credentials || "same-origin"
          });
          if (!source.ok) throw new Error(`附件 ${attachment.name} 读取失败。`);
          const blob = await source.blob();
          const path2 = `attachments/${messageId}/${this.safeAttachmentName(attachment.name, index2)}`;
          const form = new FormData();
          form.set("threadId", this.threadId);
          form.set("path", path2);
          form.set("file", blob, attachment.name);
          const response = await fetch(this.workspaceEndpoint("/workspace/upload"), {
            method: "POST",
            credentials: this.runtimeCredentials(),
            headers: this.workspaceHeaders(capability),
            body: form
          });
          if (!response.ok) throw new Error(await this.workspaceError(response));
          synced.push({ ...clone(attachment), workspacePath: path2 });
        }
        return synced;
      } catch (error) {
        await Promise.all(synced.map((attachment) => this.deleteWorkspaceEntry(
          attachment.workspacePath || ""
        ).catch(() => void 0)));
        throw error;
      }
    }
    applyEvent(rawEvent) {
      this.applyEventForContext(rawEvent, this.activeRunContext);
    }
    applyEventForContext(rawEvent, context) {
      var _a, _b;
      if (!rawEvent || typeof rawEvent !== "object") {
        return;
      }
      if (context == null ? void 0 : context.cancelled) return;
      const event = rawEvent;
      const eventRunId = String(event.runId || event.run_id || "");
      const eventThreadId = String(event.threadId || event.thread_id || "");
      const expectedRunId = (context == null ? void 0 : context.currentRunId) || this.currentRunId;
      const expectedThreadId = (context == null ? void 0 : context.threadId) || this.threadId;
      if (eventRunId && eventRunId !== expectedRunId || eventThreadId && eventThreadId !== expectedThreadId) {
        return;
      }
      const type = eventType(event);
      const data = eventData(event);
      let tool;
      (_b = (_a = this.props).onEvent) == null ? void 0 : _b.call(_a, event);
      if (type === "TEXT_MESSAGE_START") {
        this.activeTextMessageId = String(event.messageId || event.message_id || "");
        this.ensureAssistant(this.activeTextMessageId || void 0);
      } else if (type === "TEXT_MESSAGE_CONTENT" || type === "TEXT_MESSAGE_CHUNK") {
        this.appendAssistantContent(eventText(event), String(event.messageId || event.message_id || this.activeTextMessageId || ""));
      } else if (type === "TEXT_MESSAGE_END") {
        this.activeTextMessageId = null;
      } else if (type === "TOOL_CALL_START") {
        this.activeToolCallId = eventToolCallId(event);
        this.mergeTool({
          id: this.activeToolCallId,
          name: eventToolCallName(event),
          argsText: "",
          args: {},
          status: "running",
          parentMessageId: String(event.parentMessageId || event.parent_message_id || "")
        });
      } else if (type === "TOOL_CALL_ARGS" || type === "TOOL_CALL_CHUNK") {
        tool = this.mergeTool({
          id: eventToolCallId(event) || this.activeToolCallId || "",
          name: eventToolCallName(event),
          status: "running"
        });
        tool.argsText = `${tool.argsText || ""}${String(event.delta || event.args || event.toolCallArgs || "")}`;
        tool.args = parseJson(tool.argsText);
        tool.tool_args = tool.args;
      } else if (type === "TOOL_CALL_END") {
        tool = this.mergeTool({
          id: eventToolCallId(event) || this.activeToolCallId || "",
          name: eventToolCallName(event),
          status: "pending"
        });
        this.activeToolCallId = null;
        this.executeHostBridgeTool(tool, context);
      } else if (type === "TOOL_CALL_RESULT") {
        this.applyToolResult(event);
      } else if (type === "RUN_ERROR") {
        const message = String(data.message || data.content || event.message || "AG-UI 运行失败。");
        if (context) {
          context.upstreamError = message;
          context.receivedTerminalEvent = true;
        }
        this.recordRunError(message);
      } else if (type === "RUN_FINISHED") {
        if (context) context.receivedTerminalEvent = true;
        this.applyRunFinished(event, context);
      } else if (type === "REASONING_START" || type === "REASONING_MESSAGE_START") {
        this.ensureAssistant();
      } else if (type === "REASONING_MESSAGE_CONTENT" || type === "REASONING_MESSAGE_CHUNK") {
        this.appendReasoning(eventText(event));
      } else if (type === "REASONING_MESSAGE_END" || type === "REASONING_END") {
        this.ensureAssistant();
      } else if (type === "STATE_SNAPSHOT" || type === "STATE_CHANGED") {
        this.applyStateSnapshot(
          data.snapshot || event.snapshot || data.state || event.state || data.value || data
        );
      } else if (type === "STATE_DELTA") {
        const delta = data.delta || data.value || data;
        if (Array.isArray(delta)) {
          this.applyStatePatch(delta);
        } else {
          this.applyStateDelta(delta);
        }
      } else if (type === "STATE_PATCH" || type === "STATE_PATCHES") {
        this.applyStatePatch(data.patch || data.patches || data.value || event.patch);
      } else if (type === "MESSAGES_SNAPSHOT" && Array.isArray(data.messages)) {
        this.mergeIncomingMessages(data.messages);
      }
      this.notifyMessages();
      this.emit();
    }
    async initSessions() {
      var _a, _b, _c, _d, _e;
      if (this.session || !((_a = this.props.hostBridge) == null ? void 0 : _a.listSessions)) {
        return;
      }
      try {
        if (!await this.refreshSessions()) return;
        if (this.sessions.length && ((_b = this.props.hostBridge) == null ? void 0 : _b.loadSession)) {
          await this.loadSession(this.sessions[0].id);
        } else if (!this.sessions.length && ((_c = this.props.hostBridge) == null ? void 0 : _c.createSession)) {
          await this.newSession();
        }
      } catch (error) {
        (_e = (_d = this.props).onError) == null ? void 0 : _e.call(_d, error);
      }
    }
    async ensureSession() {
      var _a;
      if (this.session || !((_a = this.props.hostBridge) == null ? void 0 : _a.createSession)) {
        return true;
      }
      await this.newSession();
      return Boolean(this.session);
    }
    applyLoadedSession(session) {
      var _a, _b, _c, _d;
      if (session.protocol !== AGUI_ODOO_PROTOCOL) {
        throw new Error("不支持此聊天会话协议。");
      }
      this.session = session;
      this.threadId = session.thread_id || this.props.threadId || uuid();
      this.workspaceCapability = null;
      const storedAgentState = session.agentState || this.props.agentState || {};
      this.agentState = normalizeAgentState(storedAgentState);
      this.messages = this.normalizeStoredMessages(session.messages || []);
      this.toolsByKey = {};
      this.pendingAssistantId = null;
      this.activeTextMessageId = null;
      this.activeToolCallId = null;
      this.executedHostBridgeTools = {};
      this.confirmingHostBridgeTools = {};
      this.resumedToolResults = {};
      this.serverConfirmationDecisions = {};
      this.undoInFlight = {};
      (_b = (_a = this.props).onSessionChange) == null ? void 0 : _b.call(_a, session);
      this.notifyMessages();
      (_d = (_c = this.props).onAgentStateChange) == null ? void 0 : _d.call(_c, this.agentState);
      if (needsAgentStateCleanup(storedAgentState)) {
        this.scheduleSave();
      }
    }
    resetThread(threadId, messages) {
      this.cancel();
      this.threadId = threadId;
      this.workspaceCapability = null;
      this.messages = this.normalizeStoredMessages(messages);
      this.agentState = normalizeAgentState(this.props.agentState || {});
      this.running = false;
      this.pendingAssistantId = null;
      this.activeTextMessageId = null;
      this.activeToolCallId = null;
      this.toolsByKey = {};
      this.executedHostBridgeTools = {};
      this.confirmingHostBridgeTools = {};
      this.resumedToolResults = {};
      this.serverConfirmationDecisions = {};
      this.undoInFlight = {};
      this.notifyMessages();
    }
    createRunContext() {
      const context = {
        threadId: this.threadId,
        controller: new AbortController(),
        cancelled: false,
        finalized: false,
        savePromise: null,
        currentRunId: "",
        currentRequestId: "",
        activeClientTools: /* @__PURE__ */ new Set(),
        receivedTerminalEvent: false,
        upstreamError: "",
        pendingHostBridgePromises: [],
        hostBridgeFollowupNeeded: false
      };
      this.activeRunContext = context;
      this.running = true;
      this.error = "";
      return context;
    }
    async executeRunLifecycle(context, action, cleanup) {
      var _a, _b;
      try {
        (_b = (_a = this.props).onRunningChange) == null ? void 0 : _b.call(_a, true);
        this.notifyMessages();
        this.emit();
        await action();
      } catch (error) {
        this.handleRunFailure(context, error);
      } finally {
        try {
          cleanup == null ? void 0 : cleanup();
        } finally {
          const savePromise = this.finalizeRun(context);
          if (savePromise) await savePromise;
        }
      }
    }
    handleRunFailure(context, error) {
      var _a, _b;
      if (this.activeRunContext !== context) return;
      if (context.cancelled || (error == null ? void 0 : error.name) === "AbortError") {
        context.cancelled = true;
        this.transportState = "cancelled";
        return;
      }
      this.error = context.upstreamError || (error == null ? void 0 : error.message) || "AG-UI 运行失败。";
      this.recordRunError(this.error);
      try {
        this.setTransportState("error");
      } catch (_callbackError) {
      }
      try {
        (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, error);
      } catch (_callbackError) {
      }
    }
    cancelRun(context) {
      if (context.cancelled) return;
      context.cancelled = true;
      if (!context.controller.signal.aborted) context.controller.abort();
      this.finalizeRun(context, "cancelled");
    }
    finalizeRun(context, state) {
      if (context.finalized) return context.savePromise;
      context.finalized = true;
      if (this.activeRunContext !== context) return context.savePromise;
      if (state) this.transportState = state;
      this.activeRunContext = null;
      this.pendingAssistantId = null;
      this.running = false;
      const callbacks = [];
      if (state) callbacks.push(() => {
        var _a, _b;
        return (_b = (_a = this.props).onTransportStateChange) == null ? void 0 : _b.call(_a, state);
      });
      callbacks.push(
        () => {
          var _a, _b;
          return (_b = (_a = this.props).onRunningChange) == null ? void 0 : _b.call(_a, false);
        },
        () => this.notifyMessages(),
        () => this.emit()
      );
      callbacks.forEach((callback) => {
        try {
          callback();
        } catch (_callbackError) {
        }
      });
      context.savePromise = this.persistImmediately();
      return context.savePromise;
    }
    throwIfRunCancelled(context) {
      if (context.cancelled || context.controller.signal.aborted || this.activeRunContext !== context) {
        throw new DOMException("Aborted", "AbortError");
      }
    }
    async awaitWithRunCancellation(context, promise) {
      this.throwIfRunCancelled(context);
      let rejectCancelled = null;
      const cancelled = new Promise((_resolve, reject) => {
        rejectCancelled = reject;
      });
      const onAbort = () => rejectCancelled == null ? void 0 : rejectCancelled(new DOMException("Aborted", "AbortError"));
      context.controller.signal.addEventListener("abort", onAbort, { once: true });
      try {
        return await Promise.race([promise, cancelled]);
      } finally {
        context.controller.signal.removeEventListener("abort", onAbort);
      }
    }
    async run(context, depth) {
      this.throwIfRunCancelled(context);
      const capability = await this.ensureWorkspaceCapability();
      context.pendingHostBridgePromises = [];
      context.hostBridgeFollowupNeeded = false;
      const input = buildRunInput(
        this.messages,
        this.props,
        context.threadId,
        this.pendingAssistantId,
        this.agentState
      );
      validateRunInput(input, this.props);
      context.currentRunId = input.runId;
      context.currentRequestId = input.requestId;
      context.activeClientTools = new Set(input.tools.map((tool) => tool.name));
      context.receivedTerminalEvent = false;
      context.upstreamError = "";
      this.currentRunId = input.runId;
      this.currentRequestId = input.requestId;
      this.setTransportState("connecting");
      const response = await fetch(endpoint(this.props), {
        method: "POST",
        credentials: this.props.credentials || (this.props.allowCrossOriginDev ? "include" : "same-origin"),
        headers: {
          ...this.props.headers || {},
          Accept: "text/event-stream",
          "Content-Type": "application/json",
          "X-Request-ID": input.requestId,
          ...capability ? this.workspaceHeaders(capability) : {}
        },
        body: JSON.stringify(input),
        signal: context.controller.signal
      });
      if (!response.ok) {
        throw transportError(response.status);
      }
      if (!(response.headers.get("content-type") || "").includes("text/event-stream")) {
        throw new Error("AG-UI 运行服务必须返回 text/event-stream。");
      }
      if (!response.body) {
        throw new Error("AG-UI SSE 响应没有正文。");
      }
      this.setTransportState("streaming");
      await this.readSse(response.body, context);
      this.throwIfRunCancelled(context);
      if (!context.receivedTerminalEvent) {
        throw new Error("AG-UI 数据流在 RUN_FINISHED 事件之前结束。");
      }
      if (context.upstreamError) {
        throw new Error(context.upstreamError);
      }
      await this.waitForHostBridge(context, depth);
      this.throwIfRunCancelled(context);
      this.setTransportState("completed");
    }
    async readSse(body, context) {
      var _a;
      const reader = body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const limit = ((_a = this.props.limits) == null ? void 0 : _a.sseEventBytes) ?? 1024 * 1024;
      try {
        for (; ; ) {
          const result = await reader.read();
          if (result.done) {
            buffer += decoder.decode();
            if (buffer.trim()) this.consumeSseBlock(buffer, context);
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          if (new TextEncoder().encode(buffer).byteLength > limit && !/\r?\n\r?\n/.test(buffer)) {
            throw new Error("SSE 事件超过配置的大小限制。");
          }
          buffer = this.flushSse(buffer, limit, context);
          if (context.receivedTerminalEvent) {
            return;
          }
          this.throwIfRunCancelled(context);
        }
      } finally {
        if (context.receivedTerminalEvent) void reader.cancel().catch(() => void 0);
        reader.releaseLock();
      }
    }
    flushSse(buffer, limit, context) {
      let match = buffer.match(/\r?\n\r?\n/);
      while (match && !context.receivedTerminalEvent && !context.cancelled) {
        const block = buffer.slice(0, match.index);
        if (new TextEncoder().encode(block).byteLength <= limit) {
          this.consumeSseBlock(block, context);
        }
        buffer = buffer.slice((match.index || 0) + match[0].length);
        match = buffer.match(/\r?\n\r?\n/);
      }
      return buffer;
    }
    consumeSseBlock(block, context) {
      var _a, _b;
      const data = block.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).replace(/^ /, "")).join("\n");
      if (!data || data === "[DONE]") return;
      let event;
      try {
        event = JSON.parse(data);
      } catch {
        (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, new Error("已忽略格式错误的 SSE 事件。"));
        return;
      }
      this.applyEventForContext(event, context);
    }
    async waitForHostBridge(context, depth) {
      this.throwIfRunCancelled(context);
      const pending = context.pendingHostBridgePromises;
      const maxDepth = this.props.maxToolFollowups ?? 4;
      context.pendingHostBridgePromises = [];
      if (!pending.length) {
        return;
      }
      await this.awaitWithRunCancellation(context, Promise.all(pending));
      if (context.pendingHostBridgePromises.length) {
        await this.waitForHostBridge(context, depth);
      }
      this.throwIfRunCancelled(context);
      if (context.hostBridgeFollowupNeeded && depth < maxDepth) {
        context.hostBridgeFollowupNeeded = false;
        await this.run(context, depth + 1);
      } else if (context.hostBridgeFollowupNeeded) {
        context.hostBridgeFollowupNeeded = false;
        this.appendAssistantContent(`

已达到本轮 ${maxDepth} 次页面操作上限。请继续发送消息以完成剩余操作。`);
      }
    }
    ensureAssistant(messageId) {
      let message = messageId ? this.messages.find((item) => item.id === messageId) : null;
      const pending = this.pendingAssistantId ? this.messages.find((item) => item.id === this.pendingAssistantId) : null;
      if (!message && messageId && pending && !pending.content && !(pending.tool_calls && pending.tool_calls.length)) {
        pending.id = messageId;
        this.pendingAssistantId = messageId;
        message = pending;
      } else if (!message && !messageId) {
        message = this.lastAssistant();
      }
      if (!message) {
        message = {
          id: messageId || uuid(),
          role: "assistant",
          content: "",
          tool_calls: [],
          created_at: Date.now()
        };
        this.messages.push(message);
      }
      return message;
    }
    lastAssistant() {
      for (let index2 = this.messages.length - 1; index2 >= 0; index2 -= 1) {
        const message = this.messages[index2];
        if (message.role === "assistant" || message.role === "agent") {
          return message;
        }
      }
      return null;
    }
    appendAssistantContent(delta, messageId) {
      const message = this.ensureAssistant(messageId);
      message.content = `${asText(message.content)}${delta || ""}`;
    }
    recordRunError(message) {
      this.ensureAssistant().streaming_error = message || "AG-UI 运行失败。";
    }
    mergeTool(tool) {
      const key = toolKey(tool);
      const existing = this.toolsByKey[key] || {};
      const parentMessageId = String(
        tool.parentMessageId || existing.parentMessageId || tool.message_id || existing.message_id || ""
      );
      const message = this.ensureAssistant(parentMessageId || void 0);
      const cleanTool = Object.fromEntries(
        Object.entries(tool).filter(([, value]) => value !== void 0 && value !== "")
      );
      const name2 = toolName({ ...existing, ...cleanTool });
      const args = toolArgs({ ...existing, ...cleanTool });
      const id = toolCallId({ ...existing, ...cleanTool });
      const next = {
        ...existing,
        ...cleanTool,
        id: id || void 0,
        tool_call_id: id || void 0,
        name: name2,
        tool_name: name2,
        tool: name2,
        args,
        tool_args: args,
        key,
        status: mergeStatus(existing.status, tool.status || "pending"),
        parentMessageId: parentMessageId || message.id,
        message_id: tool.message_id || existing.message_id || message.id
      };
      this.toolsByKey[key] = next;
      message.tool_calls = (message.tool_calls || []).filter((item) => (item.key || toolKey(item)) !== key);
      message.tool_calls.push(next);
      return next;
    }
    applyToolResult(event) {
      const result = parseJson(event.content !== void 0 ? event.content : event.result);
      this.mergeTool({
        id: eventToolCallId(event),
        name: eventToolCallName(event),
        result,
        status: statusFromResult(result, "ok"),
        error: result && typeof result === "object" ? result.error : false
      });
    }
    executeHostBridgeTool(tool, context) {
      if (!context || !context.activeClientTools.has(toolName(tool))) {
        return;
      }
      const key = tool.key || toolKey(tool);
      if (!tool || this.executedHostBridgeTools[key]) {
        return;
      }
      let promise = null;
      try {
        promise = this.callHostBridge(tool, context);
      } catch (error) {
        promise = Promise.reject(error);
      }
      if (!promise) {
        return;
      }
      this.executedHostBridgeTools[key] = true;
      this.mergeTool({
        id: toolCallId(tool),
        name: toolName(tool),
        status: "running"
      });
      const handled = promise.then(
        (value) => {
          this.recordHostBridgeResult(tool, this.normalizeHostBridgeSuccess(tool, value), context);
        },
        (error) => {
          this.recordHostBridgeResult(tool, {
            ok: false,
            operation: toolName(tool),
            error: (error == null ? void 0 : error.message) || String(error || "宿主桥接调用失败。")
          }, context);
        }
      ).finally(() => {
        if (context.cancelled || this.activeRunContext !== context) {
          void this.persistImmediately();
        }
      });
      context.pendingHostBridgePromises.push(handled);
    }
    callHostBridge(tool, context) {
      const bridge = this.props.hostBridge || {};
      const args = toolArgs(tool);
      const call = {
        id: toolCallId(tool) || false,
        tool: toolName(tool),
        arguments: args,
        message_id: tool.message_id || false,
        context: {
          requestId: context.currentRequestId,
          runId: context.currentRunId,
          threadId: context.threadId,
          selectedMentionTokens: this.latestMentionTokens()
        }
      };
      return bridge.executeTool ? Promise.resolve(bridge.executeTool(call)) : null;
    }
    normalizeHostBridgeSuccess(tool, value) {
      if (value && typeof value === "object" && ("ok" in value || "operation" in value || "applied" in value || "rejected" in value)) {
        return value;
      }
      return {
        ok: true,
        operation: toolName(tool),
        content: value
      };
    }
    recordHostBridgeResult(tool, result, context = this.activeRunContext) {
      const id = toolCallId(tool);
      if (result.needs_confirmation) {
        this.mergeTool({
          id,
          name: toolName(tool),
          result,
          status: "needs_confirmation",
          error: false
        });
        this.notifyMessages();
        this.emit();
        return;
      }
      const messageId = `tool-${id || uuid()}`;
      const content2 = JSON.stringify(result || {});
      const existing = this.messages.find((message) => message.id === messageId);
      const source = this.messages.find((message) => message.id === tool.message_id);
      this.mergeTool({
        id,
        name: toolName(tool),
        result,
        status: statusFromResult(result, "ok"),
        needs_confirmation: false,
        error: result.error || false
      });
      if (existing) {
        existing.content = content2;
      } else {
        this.messages.push({
          id: messageId,
          role: "tool",
          name: toolName(tool),
          toolCallId: id,
          tool_call_id: id,
          content: content2,
          hidden: true,
          created_at: Date.now()
        });
      }
      if (source) {
        source.content = "";
      }
      if (context && !context.cancelled && this.activeRunContext === context) {
        context.hostBridgeFollowupNeeded = true;
      }
      this.notifyMessages();
      this.emit();
    }
    async persistImmediately() {
      var _a, _b;
      try {
        await this.queueSave();
      } catch (error) {
        const failure = error instanceof Error ? error : new Error(String(error || "会话保存失败。"));
        if (this.error === failure.message) return;
        this.error = failure.message;
        try {
          (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, failure);
        } catch (_callbackError) {
        }
        try {
          this.emit();
        } catch (_callbackError) {
        }
      }
    }
    applyRunFinished(event, context) {
      const outcome = event.outcome && typeof event.outcome === "object" ? event.outcome : {};
      const interrupts = outcome.type === "interrupt" && Array.isArray(outcome.interrupts) ? outcome.interrupts : [];
      interrupts.forEach((interrupt) => {
        const value = interrupt && typeof interrupt === "object" ? interrupt : {};
        this.mergeTool({
          id: String(value.toolCallId || value.id || ""),
          name: String(value.reason || "interrupt"),
          status: "needs_confirmation",
          result: { ...value, server_confirmation: true }
        });
      });
      if (!context) return;
      Object.values(this.toolsByKey).forEach((candidate) => {
        if (context.activeClientTools.has(toolName(candidate)) || candidate.result !== void 0 || !["pending", "running"].includes(candidate.status || "pending")) return;
        this.mergeTool({
          id: toolCallId(candidate),
          name: toolName(candidate),
          status: "needs_confirmation",
          needs_confirmation: true,
          result: {
            server_confirmation: true,
            operation: toolName(candidate),
            arguments: toolArgs(candidate)
          }
        });
      });
    }
    appendReasoning(content2) {
      const message = this.ensureAssistant();
      message.extra_data = message.extra_data || {};
      message.extra_data.reasoning_steps = message.extra_data.reasoning_steps || [];
      message.extra_data.reasoning_steps.push({
        title: "推理过程",
        content: content2
      });
    }
    reportHostStateMutation() {
      var _a, _b;
      (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, new Error("已忽略智能体修改 Odoo 宿主状态的尝试。"));
    }
    extractAgentState(value) {
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        return {};
      }
      const envelope = value;
      if ("host" in envelope && JSON.stringify(envelope.host) !== JSON.stringify(this.props.hostState)) {
        this.reportHostStateMutation();
      }
      if (envelope.agent && typeof envelope.agent === "object" && !Array.isArray(envelope.agent)) {
        return normalizeAgentState(envelope.agent);
      }
      const agent = { ...envelope };
      delete agent.host;
      delete agent.protocol;
      return normalizeAgentState(agent);
    }
    applyStateSnapshot(state) {
      var _a, _b;
      this.agentState = this.extractAgentState(state);
      (_b = (_a = this.props).onAgentStateChange) == null ? void 0 : _b.call(_a, this.agentState);
      this.scheduleSave();
    }
    applyStateDelta(delta) {
      var _a, _b;
      this.agentState = deepMerge(this.agentState || {}, this.extractAgentState(delta));
      (_b = (_a = this.props).onAgentStateChange) == null ? void 0 : _b.call(_a, this.agentState);
      this.scheduleSave();
    }
    applyStatePatch(patch2) {
      var _a, _b;
      if (!Array.isArray(patch2)) return;
      let nextState = this.agentState || {};
      patch2.forEach((operation) => {
        if (!operation || typeof operation !== "object") return;
        const item = operation;
        const path2 = String(item.path || "");
        if (path2 === "/host" || path2.startsWith("/host/")) {
          this.reportHostStateMutation();
          return;
        }
        if (path2 === "/protocol") return;
        if (path2 === "/agent") {
          if (item.op === "remove") nextState = {};
          if (item.op === "add" || item.op === "replace") nextState = normalizeAgentState(item.value);
          return;
        }
        nextState = applyJsonPatch(nextState, [{
          ...item,
          path: path2.startsWith("/agent/") ? path2.slice(6) : path2
        }]);
      });
      this.agentState = normalizeAgentState(nextState);
      (_b = (_a = this.props).onAgentStateChange) == null ? void 0 : _b.call(_a, this.agentState);
      this.scheduleSave();
    }
    normalizeMessage(rawMessage) {
      var _a, _b;
      const result = { ...rawMessage || {} };
      result.id = result.id || uuid();
      result.role = result.role === "agent" ? "assistant" : result.role || "assistant";
      if (result.content === void 0 || result.content === null) {
        result.content = "";
      }
      if (result.menuMention) {
        result.menuMention = this.resolveMenuMention(result.menuMention) || {
          ...clone(result.menuMention),
          valid: false
        };
      }
      if (Array.isArray(result.mentions)) {
        result.mentions = result.mentions.map((mention) => ({
          ...clone(mention),
          valid: this.isMentionCurrent(mention)
        }));
      }
      if (Array.isArray(result.skills)) {
        result.skills = result.skills.map((skill) => ({
          ...clone(skill),
          valid: this.isSkillCurrent(skill)
        }));
      }
      if (result.streamingError && !result.streaming_error) {
        result.streaming_error = "AG-UI 运行失败。";
      }
      if (result.references) {
        result.extra_data = {
          ...result.extra_data || {},
          references: ((_a = result.extra_data) == null ? void 0 : _a.references) || normalizeReferenceGroups(result.references)
        };
      }
      if ((_b = result.extra_data) == null ? void 0 : _b.references) {
        result.extra_data.references = normalizeReferenceGroups(result.extra_data.references);
      }
      if (result.role === "assistant") {
        this.mergeMessageToolCalls(result);
      }
      return result;
    }
    normalizeStoredMessages(messages) {
      const normalized = [];
      messages.forEach((rawMessage) => {
        const message = this.normalizeMessage(rawMessage);
        if (message.role === "reasoning") {
          this.consumeReasoningMessage(message, normalized);
          return;
        }
        normalized.push(message);
      });
      return normalized;
    }
    mergeIncomingMessages(messages) {
      const previousById = {};
      this.messages.forEach((message) => {
        previousById[message.id] = message;
      });
      const normalized = [];
      messages.forEach((rawMessage) => {
        let message = this.normalizeMessage(rawMessage);
        message = this.mergeMessageMetadata(message, previousById[message.id]);
        if (message.role === "reasoning") {
          this.consumeReasoningMessage(message, normalized);
          return;
        }
        normalized.push(message);
      });
      this.messages = normalized;
    }
    mergeMessageMetadata(message, previous2) {
      var _a, _b, _c, _d, _e, _f, _g, _h;
      if (!previous2) {
        return message;
      }
      if (((_a = previous2.tool_calls) == null ? void 0 : _a.length) && !((_b = message.tool_calls) == null ? void 0 : _b.length)) {
        message.tool_calls = previous2.tool_calls;
      }
      if (previous2.extra_data) {
        message.extra_data = {
          ...previous2.extra_data,
          ...message.extra_data || {}
        };
      }
      if (previous2.streaming_error && !message.streaming_error) {
        message.streaming_error = previous2.streaming_error;
      }
      if (previous2.menuMention && !message.menuMention) {
        message.menuMention = previous2.menuMention;
      }
      if (((_c = previous2.mentions) == null ? void 0 : _c.length) && !((_d = message.mentions) == null ? void 0 : _d.length)) {
        message.mentions = previous2.mentions;
      }
      if (((_e = previous2.workspaceReferences) == null ? void 0 : _e.length) && !((_f = message.workspaceReferences) == null ? void 0 : _f.length)) {
        message.workspaceReferences = previous2.workspaceReferences;
      }
      if (((_g = previous2.skills) == null ? void 0 : _g.length) && !((_h = message.skills) == null ? void 0 : _h.length)) {
        message.skills = previous2.skills;
      }
      if (previous2.recordSelection && !message.recordSelection) {
        message.recordSelection = previous2.recordSelection;
      }
      return message;
    }
    isMentionCurrent(mention) {
      if (!(mention == null ? void 0 : mention.token) || !mention.resourceKey || !mention.kind || !mention.action) return false;
      const normalized = String(mention.expiresAt || "").includes("T") ? String(mention.expiresAt) : `${String(mention.expiresAt || "").replace(" ", "T")}Z`;
      const expires = Date.parse(normalized);
      return mention.valid !== false && Number.isFinite(expires) && expires > Date.now();
    }
    latestMentionTokens() {
      const message = [...this.messages].reverse().find((item) => item.role === "user");
      return ((message == null ? void 0 : message.mentions) || []).filter((mention) => mention.valid).map((mention) => mention.token);
    }
    validateMentions(mentions) {
      if (mentions.length > 5) return "每条消息最多引用 5 个对象。";
      if (new Set(mentions.map((mention) => mention.resourceKey)).size !== mentions.length) {
        return "不能重复引用同一对象。";
      }
      const pageActions = mentions.filter((mention) => mention.pageAction || ["open", "create", "view", "edit", "apply"].includes(mention.action));
      if (pageActions.length > 1) return "每条消息最多包含 1 个页面动作。";
      if (mentions.some((mention) => !this.isMentionCurrent(mention))) {
        return "对象引用已过期，请重新选择。";
      }
      return null;
    }
    revalidateMentions() {
      let changed = false;
      this.messages.forEach((message) => {
        var _a;
        if (!((_a = message.mentions) == null ? void 0 : _a.length)) return;
        message.mentions = message.mentions.map((mention) => {
          const valid2 = this.isMentionCurrent(mention);
          if (valid2 === mention.valid) return mention;
          changed = true;
          return { ...mention, valid: valid2 };
        });
      });
      return changed;
    }
    isSkillCurrent(skill) {
      return Boolean((this.props.agentSkills || []).some(
        (option) => option.id === skill.id && option.name === skill.name
      ));
    }
    validateSkills(skills) {
      if (skills.length > 1) return "每条消息只能选择 1 个技能。";
      if (new Set(skills.map((skill) => skill.id)).size !== skills.length) {
        return "不能重复选择同一技能。";
      }
      if (skills.some((skill) => !this.isSkillCurrent(skill))) {
        return "所选技能已不可用，请移除后重试。";
      }
      return null;
    }
    revalidateSkills() {
      let changed = false;
      this.messages.forEach((message) => {
        var _a;
        if (!((_a = message.skills) == null ? void 0 : _a.length)) return;
        message.skills = message.skills.map((skill) => {
          const valid2 = this.isSkillCurrent(skill);
          if (valid2 === skill.valid) return skill;
          changed = true;
          return { ...skill, valid: valid2 };
        });
      });
      return changed;
    }
    resolveMenuMention(mention) {
      const option = (this.props.menuOptions || []).find(
        (item) => item.menuId === mention.menuId && item.actionId === mention.actionId
      );
      return option ? { ...clone(option), valid: true } : void 0;
    }
    isCurrentRecordSelection(selection) {
      var _a;
      const host = this.props.hostState;
      return selection.snapshotId === host.snapshotId && selection.hostRevision === host.hostRevision && Boolean((_a = host.capabilities) == null ? void 0 : _a.records.some((record) => record.token === selection.token));
    }
    revalidateMenuMentions() {
      let changed = false;
      this.messages.forEach((message) => {
        if (!message.menuMention) return;
        const next = this.resolveMenuMention(message.menuMention) || {
          ...clone(message.menuMention),
          valid: false
        };
        if (JSON.stringify(next) !== JSON.stringify(message.menuMention)) {
          message.menuMention = next;
          changed = true;
        }
      });
      return changed;
    }
    consumeReasoningMessage(message, targetMessages) {
      var _a;
      const steps = normalizeReasoningSteps((_a = message.extra_data) == null ? void 0 : _a.reasoning_steps, asText(message.content));
      const target = [...targetMessages].reverse().find((item) => item.role === "assistant");
      if (!target) {
        message.extra_data = {
          ...message.extra_data || {},
          reasoning_steps: steps
        };
        targetMessages.push(message);
        return;
      }
      target.extra_data = target.extra_data || {};
      target.extra_data.reasoning_steps = [...target.extra_data.reasoning_steps || [], ...steps];
    }
    mergeMessageToolCalls(message) {
      const calls = [
        ...(message.toolCalls || []).map((call) => toolCallFromTransport(call, message.id)),
        ...(message.tool_calls || []).map((call) => ({ ...call, message_id: message.id }))
      ].filter(Boolean);
      if (!calls.length) {
        return;
      }
      message.tool_calls = [];
      calls.forEach((call) => {
        var _a;
        const key = toolKey(call);
        const existing = this.toolsByKey[key];
        const normalized = {
          ...call,
          id: toolCallId(call) || void 0,
          tool_call_id: toolCallId(call) || void 0,
          name: toolName(call),
          tool_name: toolName(call),
          tool: toolName(call),
          args: toolArgs(call),
          tool_args: toolArgs(call),
          status: call.status || "pending",
          key,
          message_id: message.id
        };
        this.toolsByKey[key] = existing ? { ...existing, ...normalized } : normalized;
        (_a = message.tool_calls) == null ? void 0 : _a.push(this.toolsByKey[key]);
      });
    }
    setTransportState(state) {
      var _a, _b;
      this.transportState = state;
      (_b = (_a = this.props).onTransportStateChange) == null ? void 0 : _b.call(_a, state);
      this.emit();
    }
    scheduleSave() {
      var _a;
      if (!this.session || !((_a = this.props.hostBridge) == null ? void 0 : _a.saveSession)) {
        return;
      }
      if (this.saveTimer) {
        clearTimeout(this.saveTimer);
      }
      this.saveTimer = setTimeout(() => {
        this.saveTimer = null;
        void this.persistImmediately();
      }, 600);
    }
    queueSave() {
      this.saveQueue = this.saveQueue.then(() => this.saveSession(), () => this.saveSession());
      return this.saveQueue;
    }
    async saveSession(attempt = 0) {
      var _a, _b, _c, _d, _e, _f, _g;
      if (!this.session || !((_a = this.props.hostBridge) == null ? void 0 : _a.saveSession)) {
        return;
      }
      const result = await this.props.hostBridge.saveSession(this.session.id, {
        name: this.session.name || "新对话",
        surface: this.props.surface || this.session.surface || "dock",
        messages: this.messages,
        agentState: normalizeAgentState(this.agentState),
        uiPreferences: this.session.uiPreferences || {},
        expectedSessionRevision: this.session.sessionRevision ?? 0
      });
      if (result && typeof result === "object" && result.ok === false) {
        const failure = result;
        if (failure.error === "session_not_found" && attempt === 0 && this.props.hostBridge.createSession) {
          const previous2 = this.session;
          const replacement = sessionFromResult(await this.props.hostBridge.createSession({
            name: previous2.name || "新对话",
            surface: this.props.surface || previous2.surface || "dock",
            agent_id: previous2.agent_id || this.props.agentId || false
          }));
          if (!replacement.id || replacement.protocol !== AGUI_ODOO_PROTOCOL) {
            throw new Error("无法创建替代会话。");
          }
          this.session = {
            ...replacement,
            messages: this.messages,
            agentState: normalizeAgentState(this.agentState),
            uiPreferences: previous2.uiPreferences || replacement.uiPreferences || {}
          };
          this.threadId = replacement.thread_id;
          (_c = (_b = this.props).onSessionChange) == null ? void 0 : _c.call(_b, this.session);
          this.emit();
          return this.saveSession(1);
        }
        if (failure.error === "session_revision_conflict" && attempt === 0 && this.props.hostBridge.loadSession) {
          const remote = sessionFromResult(
            await this.props.hostBridge.loadSession(this.session.id)
          );
          this.messages = mergeMessagesById(remote.messages || [], this.messages);
          this.session = { ...this.session, ...remote, messages: this.messages };
          this.notifyMessages();
          return this.saveSession(1);
        }
        const error = new Error(
          failure.error === "session_revision_conflict" ? "会话保存连续发生版本冲突，确认结果仍保留在当前页面。" : failure.error || "会话保存失败。"
        );
        this.error = error.message;
        (_e = (_d = this.props).onError) == null ? void 0 : _e.call(_d, error);
        this.emit();
        throw error;
      }
      if (result) {
        this.session = {
          ...this.session,
          ...sessionFromResult(result)
        };
        (_g = (_f = this.props).onSessionChange) == null ? void 0 : _g.call(_f, this.session);
        this.emit();
      }
    }
    notifyMessages() {
      var _a, _b;
      (_b = (_a = this.props).onMessagesChange) == null ? void 0 : _b.call(_a, this.messages);
    }
    reportError(reason, fallback) {
      var _a, _b;
      const error = reason instanceof Error && reason.message ? reason : new Error(String(reason || fallback));
      this.error = error.message || fallback;
      try {
        (_b = (_a = this.props).onError) == null ? void 0 : _b.call(_a, error);
      } catch (_callbackError) {
      }
      this.emit();
    }
    emit() {
      this.listeners.forEach((listener) => listener());
    }
  }
  const VERSION = "12.0.8.4.0";
  function mount(el, props) {
    const root2 = clientExports.createRoot(el);
    const runtime = new ChatRuntime(props);
    let currentProps = props;
    const render = () => {
      root2.render(
        /* @__PURE__ */ jsxRuntimeExports.jsx(React.StrictMode, { children: /* @__PURE__ */ jsxRuntimeExports.jsx(AguiChatApp, { runtime, props: currentProps }) })
      );
    };
    render();
    const handle2 = {
      update(nextProps = {}) {
        currentProps = { ...currentProps, ...nextProps };
        runtime.update(nextProps);
        render();
      },
      unmount() {
        runtime.unmount();
        root2.unmount();
      }
    };
    if (props.__debug) {
      handle2.__runtime = runtime;
    }
    return handle2;
  }
  const AguiChat = {
    mount,
    version: VERSION,
    protocol: AGUI_ODOO_PROTOCOL
  };
  if (typeof window !== "undefined") {
    window.AguiChat = AguiChat;
    window.AguiChatReact = React;
    window.AguiChatReactJSXRuntime = ReactJSXRuntime;
  }
  exports.AguiChat = AguiChat;
  exports.ChatRuntime = ChatRuntime;
  Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
  return exports;
}({});
