import { Box, Braces, CircleDot, Hash, SquareFunction, Type, Variable, type LucideIcon } from "lucide-react";

type SymbolKindStyle = {
  label: string;
  icon: LucideIcon;
  /** Syntax colour slot, so symbols read like the code they name. */
  color: string;
};

const TYPE_COLOR = "var(--editor-syntax-type)";
const FUNCTION_COLOR = "var(--editor-syntax-function)";
const NAMESPACE_COLOR = "var(--editor-syntax-namespace, var(--editor-syntax-type))";
const VARIABLE_COLOR = "var(--editor-syntax-variable, var(--muted))";
const PROPERTY_COLOR = "var(--editor-syntax-property, var(--muted))";
const CONSTANT_COLOR = "var(--editor-syntax-constant, var(--editor-syntax-number))";

const KIND_STYLES: Record<string, SymbolKindStyle> = {
  file: { label: "文件", icon: Braces, color: NAMESPACE_COLOR },
  module: { label: "模块", icon: Braces, color: NAMESPACE_COLOR },
  namespace: { label: "命名空间", icon: Braces, color: NAMESPACE_COLOR },
  package: { label: "包", icon: Braces, color: NAMESPACE_COLOR },
  class: { label: "类", icon: Box, color: TYPE_COLOR },
  struct: { label: "结构体", icon: Box, color: TYPE_COLOR },
  interface: { label: "接口", icon: Box, color: TYPE_COLOR },
  enum: { label: "枚举", icon: Box, color: TYPE_COLOR },
  typeParameter: { label: "类型参数", icon: Type, color: TYPE_COLOR },
  method: { label: "方法", icon: SquareFunction, color: FUNCTION_COLOR },
  function: { label: "函数", icon: SquareFunction, color: FUNCTION_COLOR },
  constructor: { label: "构造函数", icon: SquareFunction, color: FUNCTION_COLOR },
  operator: { label: "运算符", icon: SquareFunction, color: FUNCTION_COLOR },
  property: { label: "属性", icon: CircleDot, color: PROPERTY_COLOR },
  field: { label: "字段", icon: CircleDot, color: PROPERTY_COLOR },
  event: { label: "事件", icon: CircleDot, color: PROPERTY_COLOR },
  key: { label: "键", icon: CircleDot, color: PROPERTY_COLOR },
  variable: { label: "变量", icon: Variable, color: VARIABLE_COLOR },
  object: { label: "对象", icon: Variable, color: VARIABLE_COLOR },
  array: { label: "数组", icon: Variable, color: VARIABLE_COLOR },
  constant: { label: "常量", icon: Hash, color: CONSTANT_COLOR },
  enumMember: { label: "枚举成员", icon: Hash, color: CONSTANT_COLOR },
  string: { label: "字符串", icon: Hash, color: CONSTANT_COLOR },
  number: { label: "数字", icon: Hash, color: CONSTANT_COLOR },
  boolean: { label: "布尔", icon: Hash, color: CONSTANT_COLOR },
  null: { label: "空值", icon: Hash, color: CONSTANT_COLOR },
  heading: { label: "标题", icon: Hash, color: "var(--muted)" },
};

const FALLBACK_STYLE: SymbolKindStyle = { label: "符号", icon: Variable, color: VARIABLE_COLOR };

function styleFor(kind: string) {
  // `constructor` and friends also exist on Object.prototype; only own entries count.
  return Object.prototype.hasOwnProperty.call(KIND_STYLES, kind) ? KIND_STYLES[kind] : FALLBACK_STYLE;
}

export function documentSymbolKindLabel(kind: string) {
  return styleFor(kind).label;
}

export function DocumentSymbolIcon({ kind, className = "h-3.5 w-3.5" }: { kind: string; className?: string }) {
  const { icon: Icon, color } = styleFor(kind);
  return <Icon aria-hidden="true" className={`shrink-0 ${className}`} style={{ color }} />;
}
