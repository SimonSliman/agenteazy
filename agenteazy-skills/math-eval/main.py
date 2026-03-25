import ast
import operator
_ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}


def evaluate(expression):
    try:
        def _eval(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                return _ops[type(node.op)](_eval(node.left), _eval(node.right))
            elif isinstance(node, ast.UnaryOp):
                return _ops[type(node.op)](_eval(node.operand))
            else:
                raise ValueError('Unsupported expression')
        tree = ast.parse(expression, mode='eval')
        result = _eval(tree.body)
        return {'expression': expression, 'result': result}
    except Exception as e:
        return {"error": str(e)}
