# ============================================================
# FILE: entry_exit_headcount/headcount_report.py
# PURPOSE: Generates daily and monthly headcount attendance reports from SQLite events
# USE CASE: Entry / Exit Headcount (Use Case 2)
# DEBUG TIPS:
#   - Verify HeadcountEvent rows in perimeter_monitor.db if report totals are zero
#   - Timestamps are stored in UTC and grouped by calendar date
# ============================================================


from datetime import date, datetime, time, timedelta

from sqlalchemy import func

from shared.models import HeadcountEvent


class HeadcountReport:
    """
    Generates daily and monthly entry/exit reports
    from stored headcount events.
    """

    def __init__(self, db):
        self.db = db

    # --------------------------------------------------
    # DAILY REPORT
    # --------------------------------------------------

    def get_daily_report(
        self,
        report_date=None,
        gate_name="Gate 3",
        opening_count=0,
    ):
        """
        Generate a daily headcount report.

        Args:
            report_date: Date for the report.
            gate_name: Gate name.
            opening_count: Number of people inside at
                           the beginning of the day.
        """

        if report_date is None:
            report_date = date.today()

        start_time = datetime.combine(
            report_date,
            time.min
        )

        end_time = start_time + timedelta(days=1)

        # Get total IN and OUT events for the day.
        results = (
            self.db.query(
                HeadcountEvent.direction,
                func.count(HeadcountEvent.id).label("total")
            )
            .filter(
                HeadcountEvent.gate_name == gate_name,
                HeadcountEvent.event_timestamp >= start_time,
                HeadcountEvent.event_timestamp < end_time,
            )
            .group_by(HeadcountEvent.direction)
            .all()
        )

        total_in = 0
        total_out = 0

        for direction, total in results:
            if direction == "IN":
                total_in = total

            elif direction == "OUT":
                total_out = total

        closing_count = (
            opening_count + total_in - total_out
        )

        return {
            "gate_name": gate_name,
            "report_date": report_date.isoformat(),
            "opening_count": opening_count,
            "total_in": total_in,
            "total_out": total_out,
            "closing_count": closing_count,
        }

    # --------------------------------------------------
    # MONTHLY REPORT
    # --------------------------------------------------

    def get_monthly_report(
        self,
        year=None,
        month=None,
        gate_name="Gate 3",
        opening_count=0,
    ):
        """
        Generate a monthly report with daily breakdowns.
        """

        today = date.today()

        if year is None:
            year = today.year

        if month is None:
            month = today.month

        if month < 1 or month > 12:
            raise ValueError("Month must be between 1 and 12")

        first_day = date(year, month, 1)

        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)

        start_time = datetime.combine(
            first_day,
            time.min
        )

        end_time = datetime.combine(
            next_month,
            time.min
        )

        # Get daily IN and OUT totals.
        results = (
            self.db.query(
                func.date(
                    HeadcountEvent.event_timestamp
                ).label("event_date"),
                HeadcountEvent.direction,
                func.count(HeadcountEvent.id).label("total"),
            )
            .filter(
                HeadcountEvent.gate_name == gate_name,
                HeadcountEvent.event_timestamp >= start_time,
                HeadcountEvent.event_timestamp < end_time,
            )
            .group_by(
                func.date(HeadcountEvent.event_timestamp),
                HeadcountEvent.direction,
            )
            .order_by(
                func.date(HeadcountEvent.event_timestamp)
            )
            .all()
        )

        # Organize results by date.
        daily_data = {}

        for event_date, direction, total in results:
            if event_date not in daily_data:
                daily_data[event_date] = {
                    "total_in": 0,
                    "total_out": 0,
                }

            if direction == "IN":
                daily_data[event_date]["total_in"] = total

            elif direction == "OUT":
                daily_data[event_date]["total_out"] = total

        # Build daily reports and calculate monthly totals.
        daily_reports = []

        monthly_in = 0
        monthly_out = 0
        running_count = opening_count

        current_day = first_day

        while current_day < next_month:
            day_key = current_day.isoformat()

            day_data = daily_data.get(
                day_key,
                {
                    "total_in": 0,
                    "total_out": 0,
                },
            )

            total_in = day_data["total_in"]
            total_out = day_data["total_out"]

            day_opening = running_count

            running_count = max(
                0,
                running_count + total_in - total_out
            )

            daily_reports.append({
                "report_date": day_key,
                "opening_count": day_opening,
                "total_in": total_in,
                "total_out": total_out,
                "closing_count": running_count,
            })

            monthly_in += total_in
            monthly_out += total_out

            current_day += timedelta(days=1)

        return {
            "gate_name": gate_name,
            "year": year,
            "month": month,
            "opening_count": opening_count,
            "total_in": monthly_in,
            "total_out": monthly_out,
            "closing_count": running_count,
            "daily_reports": daily_reports,
        }
