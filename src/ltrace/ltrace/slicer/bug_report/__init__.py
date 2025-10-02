try:
    from ltrace.slicer.bug_report.extended_bug_report_widget import ExtendedBugReportDialog as BugReportDialog
except ImportError:
    from ltrace.slicer.bug_report.bug_report_widget import BugReportDialog
