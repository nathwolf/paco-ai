import io
import json
import unittest
import company_mcp


class CompanyBridge(unittest.TestCase):
    def test_notifications_are_ignored_and_server_results_are_preserved(self):
        request={'jsonrpc':'2.0','id':4,'method':'tools/list'}
        calls=[]
        def dispatch(value):calls.append(value);return {'jsonrpc':'2.0','id':4,'result':{'tools':[]}}
        source=io.StringIO(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n'+json.dumps(request)+'\n')
        output=io.StringIO();company_mcp.serve(source,output,dispatch)
        self.assertEqual(calls,[request]);self.assertEqual(json.loads(output.getvalue())['result'],{'tools':[]})
    def test_reconnect_failure_is_reported_without_secret_details(self):
        def broken(_):raise OSError('secret upstream diagnostic')
        output=io.StringIO();company_mcp.serve(io.StringIO('{"jsonrpc":"2.0","id":9,"method":"tools/list"}\n'),output,broken)
        result=json.loads(output.getvalue());self.assertEqual(result['id'],9);self.assertNotIn('secret',output.getvalue())
    def test_insecure_or_credential_bearing_address_is_rejected(self):
        for url in ['http://server.example','https://user:password@server.example','https://server.example?key=secret']:
            with self.assertRaises(ValueError):company_mcp.forward({},lambda:(url,'token'))
