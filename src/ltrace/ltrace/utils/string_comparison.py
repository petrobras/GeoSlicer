class StringComparison:
    EXACTLY = 0
    CONTAINS = 1

    @staticmethod
    def compare(str_a, str_b, comparison_type=EXACTLY):
        """Handles string comparison logic.

        Args:
            str_a (str): the first string
            str_b (str): the second string
            comparison_type (int, optional): The comparison mode. Defaults to EXACTLY.

        Raises:
            NotImplementedError: Raises if use invalid comparison mode

        Returns:
            bool: Returns true if string comparison is valid, otherwise returns False.
        """
        if comparison_type == StringComparison.EXACTLY:
            return str_a == str_b
        elif comparison_type == StringComparison.CONTAINS:
            return str_a in str_b or str_b in str_a
        else:
            raise NotImplementedError("StringComparison: Comparison type not implemented yet.")
