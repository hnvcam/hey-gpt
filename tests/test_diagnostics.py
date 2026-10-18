"""Diagnostic records cannot include speech fields or exception messages."""
import contextlib
import io
import json
import unittest
from diagnostics import trace, trace_error


class Diagnostics(unittest.TestCase):
    def test_speech_fields_are_excluded_and_exception_details_are_sanitized(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            trace('daemon','command-check',seconds=1.2,outcome='no-match',text='secret speech',audio='secret audio')
            try:raise ValueError('secret dictated content')
            except ValueError as error:trace_error('tray','failure',error)
        self.assertNotIn('secret',output.getvalue())
        rows=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]['outcome'],'no-match')
        self.assertEqual(rows[1]['error_type'],'ValueError')
        self.assertTrue(rows[1]['frames'])
