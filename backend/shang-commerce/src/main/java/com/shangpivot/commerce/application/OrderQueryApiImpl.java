package com.shangpivot.commerce.application;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.shangpivot.commerce.api.OrderQueryApi;
import com.shangpivot.commerce.entity.Order;
import com.shangpivot.commerce.mapper.OrderMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.Collection;
import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class OrderQueryApiImpl implements OrderQueryApi {

    private final OrderMapper orderMapper;

    @Override
    public long countByCustomerId(Long customerId) {
        if (customerId == null) {
            return 0L;
        }
        return orderMapper.selectCount(new LambdaQueryWrapper<Order>().eq(Order::getCustomerId, customerId));
    }

    @Override
    public Map<Long, Long> countByCustomerIds(Collection<Long> customerIds) {
        if (customerIds == null || customerIds.isEmpty()) {
            return Collections.emptyMap();
        }
        return orderMapper.selectList(new LambdaQueryWrapper<Order>().in(Order::getCustomerId, customerIds))
                .stream()
                .filter(o -> o.getCustomerId() != null)
                .collect(Collectors.groupingBy(Order::getCustomerId, Collectors.counting()));
    }

    @Override
    public Set<Long> findCustomerIdsByClientType(String clientType) {
        if (clientType == null || clientType.isBlank()) {
            return Collections.emptySet();
        }
        return orderMapper.selectList(new LambdaQueryWrapper<Order>()
                        .eq(Order::getClientType, clientType)
                        .select(Order::getCustomerId))
                .stream()
                .map(Order::getCustomerId)
                .filter(id -> id != null)
                .collect(Collectors.toSet());
    }
}
